"""Support for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BoschK40Client
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_HOST,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import BoschK40DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bosch Connect-Key K 40 RF from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    access_token = entry.data[CONF_ACCESS_TOKEN]

    session = async_get_clientsession(hass, verify_ssl=False)
    client = BoschK40Client(host, session)

    coordinator = BoschK40DataUpdateCoordinator(
        hass=hass,
        client=client,
        access_token=access_token,
        entry=entry,
    )

    # Initial discovery and data refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
