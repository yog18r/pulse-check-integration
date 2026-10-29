"""Serve the dashboard card and register it with the dashboards.

The card is a JavaScript bundle built from `frontend/` at the repository
root into `frontend/pulse-check-card.js` next to this file. Two Home
Assistant concepts are involved:

- A *static path* makes a file on disk available over Home Assistant's
  web server, here at `/pulse_check/pulse-check-card.js`.
- A *dashboard resource* (Settings > Dashboards > Resources) is a script
  every dashboard loads. Once loaded, the card registers itself and shows
  up in the card picker.

Resources are stored by the dashboards (Lovelace) integration. In its
default "storage" mode we add ours, or update it when the version changes;
in "YAML" mode resources live in configuration.yaml, which an integration
must not edit, so we log the line to add instead.

The file is served from the integration's `async_setup`, the earliest
moment Home Assistant runs any of its code: before the config entry sets
up, and whether or not that succeeds. A dashboard opened while Home
Assistant is still starting can then load the card, which shows that it is
connecting and fills in once Pulse Check answers. Served only at the end of
entry setup, the file was a 404 for those first seconds, the dashboard
showed "Configuration error", and only a page refresh fetched it again.

The resource URL carries the integration's version (`?v=0.2.0`), so a
browser never keeps an old bundle after an update. The file is also served
without long-lived cache headers, so a rebuilt bundle with the same
version is picked up on the next reload.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

# The documented import path; HA re-exports it without marking it for mypy.
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_URL = f"/{DOMAIN}/pulse-check-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "pulse-check-card.js"

# Set once the static path exists. Web routes cannot be removed or added
# twice, so reloading the config entry must not register it again.
_SERVED: HassKey[bool] = HassKey(f"{DOMAIN}_card_served")
# Set once a missing bundle has been logged, so it is said once, not twice.
_MISSING_LOGGED: HassKey[bool] = HassKey(f"{DOMAIN}_card_missing_logged")


async def async_serve_card(hass: HomeAssistant) -> bool:
    """Make the card file available over HTTP. True when it is.

    Called from `async_setup` and again from entry setup; it registers the
    route once. A missing bundle is logged once and skipped: the rest of
    the integration works without the card.
    """
    if hass.data.get(_SERVED):
        return True
    path = CARD_PATH
    if not await hass.async_add_executor_job(path.is_file):
        if not hass.data.get(_MISSING_LOGGED):
            _LOGGER.warning(
                "The Pulse Check card is missing (%s), so it will not be available on "
                "dashboards. When installing from a copy of the repository, run "
                "`npm ci` and `npm run build` in its frontend/ folder first",
                path,
            )
            hass.data[_MISSING_LOGGED] = True
        return False
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    hass.data[_SERVED] = True
    return True


async def async_setup_card(hass: HomeAssistant) -> None:
    """Serve the card and make sure the dashboards load it.

    Safe to call on every entry setup: nothing is registered twice.
    """
    if not await async_serve_card(hass):
        return

    await _async_register_resource(hass, await _versioned_url(hass))


async def async_remove_card_resource(hass: HomeAssistant) -> None:
    """Remove our dashboard resource when the integration is removed.

    Otherwise every dashboard would keep trying to load a file that no
    longer exists.
    """
    resources = _storage_resources(hass)
    if resources is None:
        return
    await resources.async_get_info()  # loads the collection on first use
    for item in list(resources.async_items()):
        if _is_card(item):
            await resources.async_delete_item(item["id"])


async def _versioned_url(hass: HomeAssistant) -> str:
    """The card URL with the integration's version as a cache buster."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"{CARD_URL}?v={integration.version}"


def _storage_resources(hass: HomeAssistant) -> ResourceStorageCollection | None:
    """The dashboards' resource collection, if it is the UI-managed kind."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or not isinstance(lovelace.resources, ResourceStorageCollection):
        return None
    return lovelace.resources


def _is_card(item: dict[str, str]) -> bool:
    """Whether a resource points at our bundle, whatever its version query."""
    return urlsplit(item.get("url", "")).path == CARD_URL


async def _async_register_resource(hass: HomeAssistant, url: str) -> None:
    """Add or update the card's dashboard resource, never duplicating it."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        _LOGGER.info(
            "Dashboards are not loaded; to use the Pulse Check card, add %s as a "
            "JavaScript module resource",
            url,
        )
        return

    resources = _storage_resources(hass)
    if resources is None:
        # YAML mode: say what to add, unless it is already there.
        if not any(_is_card(item) for item in lovelace.resources.async_items()):
            _LOGGER.info(
                "Dashboard resources are managed in YAML. To use the Pulse Check card, "
                "add this under lovelace: resources: - url: %s, type: module",
                url,
            )
        return

    await resources.async_get_info()  # loads the collection on first use
    ours = [item for item in resources.async_items() if _is_card(item)]
    if not ours:
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.debug("Added dashboard resource %s", url)
        return

    # Keep the first, bring it up to date, and drop any copies (for example
    # one added by hand before the integration did it).
    first, *copies = ours
    if first.get("url") != url or first.get("type") != "module":
        await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
        _LOGGER.debug("Updated dashboard resource to %s", url)
    for item in copies:
        await resources.async_delete_item(item["id"])
