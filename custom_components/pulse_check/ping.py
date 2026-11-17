"""Asking a device whether it is still there before it is marked quiet.

A device is quiet when nothing has been heard from it for its threshold.
Many devices report only when something changes, so before one is marked
quiet Pulse Check asks it directly, where there is a way to:

- a Z-Wave node, with Z-Wave JS's own ping;
- any other device whose address on the local network is known, with a
  network (ICMP) ping. The address comes from the device's configuration
  link, an entity of its own that reports it, or the address its
  integration connects to when the device is that entry's only one.

A device that answers counts as heard from, and its quiet timer starts
again. One that does not answer, or cannot be asked, is quiet. Nothing is
looked up by name: an address must be a private IP address, so a cloud
service's server is never taken for the device.

The `pulse_check.ping` action asks one device on demand and says how it
was asked and what came back (`PingResult`).
"""

from __future__ import annotations

import asyncio
import importlib
import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast
from urllib.parse import urlsplit

from homeassistant.const import CONF_HOST, CONF_IP_ADDRESS
from homeassistant.helpers import device_registry as dr, entity_registry as er
from icmplib import ICMPLibError, SocketPermissionError, async_ping

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# How long one device has to answer. A sleeping Z-Wave node answers only
# when it wakes, which is not worth waiting for: it is quiet until then.
PING_TIMEOUT = 10
# Entity attributes that hold a device's own address.
_ADDRESS_ATTRIBUTES = ("ip_address", "ip", "host")
# An entity whose state is the device's own address: `sensor.plant_ip`,
# `sensor.plant_ip_address`, `sensor.plant_ipv4_address`.
_ADDRESS_ENTITY = re.compile(r"(?:^|_)ip(?:v4|v6)?(?:_address)?$")
# ...but not another host's: `sensor.plant_gateway_ip`, `sensor.plant_dns_ip`.
_OTHER_HOST = re.compile(r"gateway|dns|router|server|wan|external|public")
_ZWAVE = "zwave_js"
# Whether the system's refusal to ping has been logged yet.
_warned_no_icmp = False

# How a device was asked.
PingMethod = Literal["zwave_js", "network", "none"]
# What came of it. Everything but "answered" leaves a device quiet.
PingOutcome = Literal[
    "answered",
    # Asked, and nothing came back in time.
    "no_answer",
    # Nothing says what its address is, and it is not a Z-Wave node.
    "no_address",
    # Part of another device (Home Assistant 2026.10's child devices).
    "part_of_another_device",
    # Z-Wave JS is not running, or could not send the ping.
    "zwave_unavailable",
    # This system forbids network pings (see the warning it logs).
    "pings_not_allowed",
    # A bug, or Home Assistant or Z-Wave JS changing: logged as a warning.
    "failed",
]
# Where a device's address was found, most reliable first.
AddressSource = Literal["configuration_url", "integration", "entity"]


@dataclass(frozen=True, slots=True)
class PingResult:
    """How a device was asked whether it is there, and what came of it."""

    outcome: PingOutcome
    method: PingMethod = "none"
    # The address pinged, for a network ping.
    address: str | None = None

    @property
    def answered(self) -> bool:
        """Whether the device answered."""
        return self.outcome == "answered"


class _ZwaveNode(Protocol):
    """The part of a Z-Wave JS node used here."""

    async def async_ping(self) -> bool:
        """Whether the node responded."""


async def async_ping_device(hass: HomeAssistant, device_id: str) -> bool:
    """Whether the device answered. False when it did not or cannot be asked."""
    return (await async_ask_device(hass, device_id)).answered


async def async_ask_device(hass: HomeAssistant, device_id: str) -> PingResult:
    """Ask a device in the device registry whether it is there.

    The caller makes sure the device exists; an unknown id cannot be asked
    and comes back as "no_address".
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return PingResult("no_address")
    # A child device (Home Assistant 2026.10) is part of its parent, and
    # has no address or integration of its own to ask.
    if not isinstance(device, dr.DeviceEntry):
        return PingResult("part_of_another_device")
    method: PingMethod = "none"
    address: str | None = None
    outcome: PingOutcome
    try:
        if _belongs_to(hass, device, _ZWAVE):
            method = "zwave_js"
        elif (found := find_address(hass, device)) is not None:
            method, address = "network", found[0]
        else:
            return PingResult("no_address")
        async with asyncio.timeout(PING_TIMEOUT):
            if address is None:
                outcome = await _ping_zwave(hass, device_id)
            else:
                outcome = _network_outcome(await _ping_address(address))
    except TimeoutError:
        _LOGGER.debug("%s did not answer within %s s", device.name, PING_TIMEOUT)
        outcome = "no_answer"
    except Exception:
        # Not a device that failed to answer (those are handled where they
        # are asked) but a bug, or Home Assistant or Z-Wave JS changing.
        # The device is still judged, as one that cannot be asked.
        _LOGGER.warning("Pinging %s failed unexpectedly", device.name, exc_info=True)
        outcome = "failed"
    return PingResult(outcome, method, address)


def _network_outcome(answered: bool | None) -> PingOutcome:
    if answered is None:
        return "pings_not_allowed"
    return "answered" if answered else "no_answer"


def ping_method(hass: HomeAssistant, device_id: str) -> tuple[PingMethod, AddressSource | None]:
    """How a device would be asked, and where its address comes from, without asking it."""
    device = dr.async_get(hass).async_get(device_id)
    if not isinstance(device, dr.DeviceEntry):
        return "none", None
    if _belongs_to(hass, device, _ZWAVE):
        return "zwave_js", None
    found = find_address(hass, device)
    if found is None:
        return "none", None
    return "network", found[1]


def _entry_ids(device: dr.DeviceEntry) -> list[str]:
    """The config entries a device belongs to.

    Home Assistant 2026.10 gives a device one entry (`config_entry_id`) and
    deprecates the old set; 2026.9 has only the set.
    """
    entry_id = getattr(device, "config_entry_id", None)
    if isinstance(entry_id, str):
        return [entry_id]
    return list(getattr(device, "config_entries", ()))


def _belongs_to(hass: HomeAssistant, device: dr.DeviceEntry, domain: str) -> bool:
    for entry_id in _entry_ids(device):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == domain:
            return True
    return False


async def _ping_zwave(hass: HomeAssistant, device_id: str) -> PingOutcome:
    """Z-Wave JS's ping, through its own helper.

    Its ping button would do the same, but a button press does not say
    whether the node answered.
    """
    node = _zwave_node(hass, device_id)
    if node is None:
        return "zwave_unavailable"
    try:
        return "answered" if await node.async_ping() else "no_answer"
    except Exception as err:
        # The client library's own errors (not connected, the command
        # failed) are a node that could not be asked; anything else is not.
        if not type(err).__module__.startswith("zwave_js_server"):
            raise
        _LOGGER.debug("Z-Wave JS could not ping %s: %s", device_id, err)
        return "zwave_unavailable"


def _zwave_node(hass: HomeAssistant, device_id: str) -> _ZwaveNode | None:
    """The device's Z-Wave JS node, or None when Z-Wave JS cannot give it.

    Imported only here: Z-Wave JS and its client library are installed
    only where it is set up.
    """
    try:
        helpers = importlib.import_module("homeassistant.components.zwave_js.helpers")
        return cast("_ZwaveNode", helpers.async_get_node_from_device_id(hass, device_id))
    except ImportError, ValueError:
        return None


def device_address(hass: HomeAssistant, device: dr.DeviceEntry) -> str | None:
    """The device's own private IP address, when anything says what it is."""
    found = find_address(hass, device)
    return found[0] if found is not None else None


def find_address(hass: HomeAssistant, device: dr.DeviceEntry) -> tuple[str, AddressSource] | None:
    """The device's own private IP address, and where it was found.

    Most reliable first: its configuration link, then the address its
    integration connects to, then an entity of its own. An entity's state
    counts only when the entity is named as an address (`..._ip_address`):
    a device can also report its gateway or DNS server, and pinging the
    router would always get an answer.
    """
    address = _private_ip(urlsplit(device.configuration_url or "").hostname)
    if address is not None:
        return address, "configuration_url"
    address = _entry_address(hass, device)
    if address is not None:
        return address, "integration"
    for entity in er.async_entries_for_device(er.async_get(hass), device.id):
        state = hass.states.get(entity.entity_id)
        if state is None:
            continue
        values = [state.attributes.get(a) for a in _ADDRESS_ATTRIBUTES]
        object_id = entity.entity_id.split(".", 1)[1]
        if _ADDRESS_ENTITY.search(object_id) and not _OTHER_HOST.search(object_id):
            values.append(state.state)
        for value in values:
            address = _private_ip(value)
            if address is not None:
                return address, "entity"
    return None


def _entry_address(hass: HomeAssistant, device: dr.DeviceEntry) -> str | None:
    """The address the integration connects to, when this device is all it connects to.

    A hub's entry has one address for many devices; only the hub itself
    may use it. A device behind another (`via_device`) never does, nor
    does one of several top-level devices sharing an entry.
    """
    if device.via_device_id is not None:
        return None
    registry = dr.async_get(hass)
    for entry_id in _entry_ids(device):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            continue
        address = _private_ip(entry.data.get(CONF_HOST)) or _private_ip(
            entry.data.get(CONF_IP_ADDRESS)
        )
        if address is None:
            continue
        top_level = [
            d for d in dr.async_entries_for_config_entry(registry, entry_id) if not d.via_device_id
        ]
        if [d.id for d in top_level] == [device.id]:
            return address
    return None


def _private_ip(value: object) -> str | None:
    """`value` as one device's address on a local network, or None.

    Private ranges only (192.168.x.x, 10.x.x.x, fd00::/8 and the like), less
    the special ones Python also counts as private: this machine (loopback),
    no address (unspecified), self-assigned link-local addresses
    (169.254.x.x, fe80::), which are also where cloud hosts keep their
    metadata service, and the broadcast address (reserved).
    """
    if not isinstance(value, str):
        return None
    try:
        address = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None
    if (
        not address.is_private
        or address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
    ):
        return None
    return str(address)


async def _ping_address(address: str) -> bool | None:
    """An ICMP ping, without root where the system allows it (Home Assistant OS does).

    None when the system allows neither.
    """
    for privileged in (False, True):
        try:
            host = await async_ping(address, count=2, interval=1, timeout=2, privileged=privileged)
        except SocketPermissionError:
            continue
        except ICMPLibError, OSError:
            return False
        return bool(host.is_alive)
    global _warned_no_icmp  # noqa: PLW0603 (once per run)
    if not _warned_no_icmp:
        _warned_no_icmp = True
        _LOGGER.warning(
            "This system does not allow network pings, so devices are not asked before they "
            "are marked quiet (only Z-Wave nodes are). Allow unprivileged ICMP "
            "(net.ipv4.ping_group_range) or turn off Ping before marking quiet"
        )
    return None
