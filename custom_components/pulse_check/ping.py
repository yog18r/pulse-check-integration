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
"""

from __future__ import annotations

import asyncio
import importlib
import ipaddress
import logging
from typing import TYPE_CHECKING, Protocol, cast
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
_ZWAVE = "zwave_js"


class _ZwaveNode(Protocol):
    """The part of a Z-Wave JS node used here."""

    async def async_ping(self) -> bool:
        """Whether the node responded."""


async def async_ping_device(hass: HomeAssistant, device_id: str) -> bool:
    """Whether the device answered. False when it did not or cannot be asked."""
    device = dr.async_get(hass).async_get(device_id)
    # A child device (Home Assistant 2026.10) is part of its parent, and
    # has no address or integration of its own to ask.
    if not isinstance(device, dr.DeviceEntry):
        return False
    try:
        async with asyncio.timeout(PING_TIMEOUT):
            if _belongs_to(hass, device, _ZWAVE):
                return await _ping_zwave(hass, device_id)
            address = device_address(hass, device)
            if address is None:
                return False
            return await _ping_address(address)
    except TimeoutError:
        _LOGGER.debug("%s did not answer within %s s", device.name, PING_TIMEOUT)
    except Exception:
        # Not a device that failed to answer (those are handled where they
        # are asked) but a bug, or Home Assistant or Z-Wave JS changing.
        # The device is still judged, as one that cannot be asked.
        _LOGGER.warning("Pinging %s failed unexpectedly", device.name, exc_info=True)
    return False


def _belongs_to(hass: HomeAssistant, device: dr.DeviceEntry, domain: str) -> bool:
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == domain:
            return True
    return False


async def _ping_zwave(hass: HomeAssistant, device_id: str) -> bool:
    """Z-Wave JS's ping, through its own helper.

    Its ping button would do the same, but a button press does not say
    whether the node answered.
    """
    node = _zwave_node(hass, device_id)
    if node is None:
        return False
    try:
        return bool(await node.async_ping())
    except Exception as err:
        # The client library's own errors (not connected, the command
        # failed) are a node that could not be asked; anything else is not.
        if not type(err).__module__.startswith("zwave_js_server"):
            raise
        _LOGGER.debug("Z-Wave JS could not ping %s: %s", device_id, err)
        return False


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
    address = _private_ip(urlsplit(device.configuration_url or "").hostname)
    if address is not None:
        return address
    for entity in er.async_entries_for_device(er.async_get(hass), device.id):
        state = hass.states.get(entity.entity_id)
        if state is None:
            continue
        for value in (*(state.attributes.get(a) for a in _ADDRESS_ATTRIBUTES), state.state):
            address = _private_ip(value)
            if address is not None:
                return address
    return _entry_address(hass, device)


def _entry_address(hass: HomeAssistant, device: dr.DeviceEntry) -> str | None:
    """The address the integration connects to, when this device is all it connects to.

    A hub's entry has one address for many devices; only the hub itself
    may use it. A device behind another (`via_device`) never does, nor
    does one of several top-level devices sharing an entry.
    """
    if device.via_device_id is not None:
        return None
    registry = dr.async_get(hass)
    for entry_id in device.config_entries:
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


async def _ping_address(address: str) -> bool:
    """An ICMP ping, without root where the system allows it (Home Assistant OS does)."""
    for privileged in (False, True):
        try:
            host = await async_ping(address, count=2, interval=1, timeout=2, privileged=privileged)
        except SocketPermissionError:
            continue
        except ICMPLibError, OSError:
            return False
        return bool(host.is_alive)
    _LOGGER.debug("This system does not allow network pings, so %s cannot be asked", address)
    return False
