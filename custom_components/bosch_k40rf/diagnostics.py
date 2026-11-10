"""Diagnostics support for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_GATEWAY_MAC,
    CONF_GATEWAY_SERIAL,
    CONF_HOST,
    CONF_LOGIN,
    CONF_PASSWORD,
    DOMAIN,
)
from .coordinator import BoschK40DataUpdateCoordinator

TO_REDACT: set[str] = {
    CONF_ACCESS_TOKEN,
    CONF_HOST,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_GATEWAY_SERIAL,
    CONF_GATEWAY_MAC,
    "unique_id",
    "uuid",
    "serial",
    "serial_number",
    "SerialNumber",
    "ModuleSerialNumber",
    "ProductSerialNumber",
    "sgtin",
    "ssid",
    "mac",
    "eth_mac",
    "wifi_mac",
    "eth_ip",
    "wifi_ip",
    "gatewayId",
    "moduleId",
    "recipeId",
}

SENSITIVE_ENDPOINT_SUFFIXES: tuple[str, ...] = (
    "/gateway/uuid",
    "/gateway/Network/Ethernet/mac",
    "/gateway/Network/Ethernet/ip",
    "/gateway/Network/Wifi/mac",
    "/gateway/Network/Wifi/ip",
    "/gateway/Network/Wifi/ssid",
    "/gateway/WiFi/Hotspot/password",
    "/gateway/eth/mac",
    "/gateway/eth/ip/ipv4",
    "/gateway/wifi/mac",
    "/gateway/wifi/ip/ipv4",
    "/gateway/wifi/ssid",
    "/gateway/update/report",
    "/sgtin",
    "/GWEEBUS.CEM.ID",
    "/GWEEBUS.CEM.SKI",
)


def _redact_api_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy and redact sensitive API endpoint values and keys."""
    copied: dict[str, Any] = deepcopy(data)
    for ep, payload in copied.items():
        if isinstance(payload, dict):
            if ep.endswith(SENSITIVE_ENDPOINT_SUFFIXES):
                if "value" in payload and payload["value"] not in (None, ""):
                    payload["value"] = "**REDACTED**"
                if "gatewayId" in payload:
                    payload["gatewayId"] = "**REDACTED**"
                if "moduleId" in payload:
                    payload["moduleId"] = "**REDACTED**"
                if isinstance(payload.get("values"), list):
                    for item in payload["values"]:
                        if isinstance(item, dict):
                            for k in ("gatewayId", "moduleId", "ModuleSerialNumber", "ProductSerialNumber"):
                                if k in item and item[k]:
                                    item[k] = "**REDACTED**"
            elif ep == "/system/basicInfo" and isinstance(payload.get("values"), list):
                for item in payload["values"]:
                    if isinstance(item, dict):
                        for k in ("ModuleSerialNumber", "ProductSerialNumber"):
                            if k in item and item[k]:
                                item[k] = "**REDACTED**"
    return async_redact_data(copied, TO_REDACT)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: BoschK40DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    sorted_data = dict(sorted((coordinator.data or {}).items()))

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "gateway_info": async_redact_data(coordinator.gateway_info, TO_REDACT),
        "system_summary": {
            "system_type": coordinator.system_type,
            "is_hybrid_system": coordinator.is_hybrid_system,
            "is_heat_pump_system": coordinator.is_heat_pump_system,
            "is_standalone_heat_pump": coordinator.is_standalone_heat_pump,
            "is_standalone_boiler": coordinator.is_standalone_boiler,
            "active_endpoints_count": len(coordinator.active_endpoints),
            "active_sensors_count": len(coordinator.active_sensor_descriptions),
            "active_binary_sensors_count": len(coordinator.active_binary_descriptions),
            "active_endpoints": sorted(coordinator.active_endpoints),
        },
        "registered_sensors": [
            {
                "key": desc.key,
                "resource_id": desc.resource_id,
                "name": desc.name,
                "translation_key": desc.translation_key,
                "target_device_type": desc.target_device_type,
                "device_sub_id": desc.device_sub_id,
                "unit": desc.native_unit_of_measurement,
            }
            for desc in coordinator.active_sensor_descriptions
        ],
        "registered_binary_sensors": [
            {
                "key": desc.key,
                "resource_id": desc.resource_id,
                "name": desc.name,
                "translation_key": desc.translation_key,
                "target_device_type": desc.target_device_type,
                "device_sub_id": desc.device_sub_id,
            }
            for desc in coordinator.active_binary_descriptions
        ],
        "api_data": _redact_api_payload(sorted_data),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for a specific device."""
    coordinator: BoschK40DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Identify which sub-device this DeviceEntry represents from its identifier
    device_ident = next(
        (ident[1] for ident in device.identifiers if ident[0] == DOMAIN),
        "",
    )

    sorted_data = dict(sorted((coordinator.data or {}).items()))

    return {
        "device": {
            "name": device.name,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "sw_version": device.sw_version,
            "hw_version": device.hw_version,
            "identifier": "**REDACTED**" if device_ident else None,
        },
        "system_summary": {
            "system_type": coordinator.system_type,
            "is_hybrid_system": coordinator.is_hybrid_system,
            "is_heat_pump_system": coordinator.is_heat_pump_system,
            "is_standalone_heat_pump": coordinator.is_standalone_heat_pump,
            "is_standalone_boiler": coordinator.is_standalone_boiler,
            "active_endpoints_count": len(coordinator.active_endpoints),
        },
        "api_data": _redact_api_payload(sorted_data),
    }
