"""Support for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

import logging

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BoschK40Client
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_GATEWAY_BRAND,
    CONF_GATEWAY_MAC,
    CONF_GATEWAY_MODEL,
    CONF_HOST,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import BoschK40DataUpdateCoordinator
from .models import (
    async_preload_translations,
    sanitize_serial_number,
    translate_device_term,
)

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
    await async_preload_translations(hass)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Clean up any previously stored corrupted/binary serial numbers in Home Assistant device registry
    dev_reg = dr.async_get(hass)

    # Register the parent Gateway device upfront so its registry ID is available for via_device_id
    gateway_unique_id = (
        entry.unique_id
        or coordinator.gateway_info.get("unique_id")
        or coordinator.client.host
    )
    brand = (
        coordinator.gateway_info.get("brand")
        or entry.data.get(CONF_GATEWAY_BRAND)
        or "Bosch"
    )
    model = (
        coordinator.gateway_info.get("model")
        or entry.data.get(CONF_GATEWAY_MODEL)
        or "Connect-Key K 40 RF"
    )
    firmware = (
        coordinator.gateway_info.get("firmware")
        or entry.data.get("firmware")
    )
    hardware = coordinator.gateway_info.get("hardware")
    mac = (
        coordinator.gateway_info.get("mac")
        or entry.data.get(CONF_GATEWAY_MAC)
    )
    gw_mod = (
        coordinator.get_basic_info_module(hw_ident="MX400")
        or coordinator.get_basic_info_module(hw_ident="K40RF")
    )
    gw_ver = (gw_mod.get("Ver") if gw_mod else None) or firmware
    gw_sn = sanitize_serial_number(
        (
            gw_mod.get("ModuleSerialNumber")
            if gw_mod and gw_mod.get("ModuleSerialNumber")
            else None
        )
        or coordinator.gateway_info.get("serial_number")
    )
    connections = set()
    if mac:
        connections.add((dr.CONNECTION_NETWORK_MAC, mac))

    gateway_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, gateway_unique_id)},
        name=f"{brand} Connect-Key K 40 RF Gateway",
        manufacturer=brand,
        model=model,
        sw_version=gw_ver,
        hw_version=hardware,
        serial_number=gw_sn,
        connections=connections,
    )
    coordinator.gateway_device_id = gateway_device.id

    lang = getattr(hass.config, "language", "en") or "en"
    phantom_non_hybrid_idents = {
        (DOMAIN, f"{gateway_unique_id}_heat_source_hybman"),
        (DOMAIN, f"{gateway_unique_id}_heat_source_kessel"),
    }
    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    for dev in devices:
        if not coordinator.is_hybrid_system and (dev.identifiers & phantom_non_hybrid_idents):
            _LOGGER.info(
                "Removing falsely detected hybrid/boiler sub-device %s (%s) on non-hybrid system",
                dev.name,
                dev.id,
            )
            dev_reg.async_remove_device(dev.id)
            continue
        update_kwargs: dict[str, Any] = {}
        if dev.serial_number:
            clean_sn = sanitize_serial_number(dev.serial_number)
            if clean_sn != dev.serial_number:
                _LOGGER.info(
                    "Sanitizing device serial number in registry for %s: %r -> %r",
                    dev.name or dev.id,
                    dev.serial_number,
                    clean_sn,
                )
                update_kwargs["serial_number"] = clean_sn
        if dev.name:
            translated_name = translate_device_term(dev.name, lang)
            if translated_name != dev.name:
                update_kwargs["name"] = translated_name
        if dev.model:
            translated_model = translate_device_term(dev.model, lang)
            if translated_model != dev.model:
                update_kwargs["model"] = translated_model
        if update_kwargs:
            dev_reg.async_update_device(dev.id, **update_kwargs)

    # Clean up orphan gas valve entities on standalone heat pump systems (where gas valves do not exist)
    if coordinator.is_standalone_heat_pump:
        entity_reg = er.async_get(hass)
        for entity_entry in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
            unique_id_lower = entity_entry.unique_id.lower()
            if (
                "gasvalve1" in unique_id_lower
                or "gasvalve2" in unique_id_lower
                or "gas_valve_1" in unique_id_lower
                or "gas_valve_2" in unique_id_lower
            ):
                _LOGGER.info(
                    "Removing gas valve entity %s (%s) on non-hybrid heat pump system",
                    entity_entry.entity_id,
                    entity_entry.unique_id,
                )
                entity_reg.async_remove(entity_entry.entity_id)

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
