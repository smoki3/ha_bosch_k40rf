"""Constants for the Bosch Connect-Key K 40 RF (Buderus MX400) integration."""

from __future__ import annotations

from typing import Final
from homeassistant.const import Platform

DOMAIN: Final = "bosch_k40rf"

# Configuration keys
CONF_HOST: Final = "host"
CONF_LOGIN: Final = "login"
CONF_PASSWORD: Final = "password"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_GATEWAY_BRAND: Final = "brand"
CONF_GATEWAY_MODEL: Final = "model"
CONF_GATEWAY_SERIAL: Final = "serial_number"
CONF_GATEWAY_MAC: Final = "mac"

# Network & Ports
AUTH_PORT: Final = 9442
DATA_PORT: Final = 9443
DEFAULT_SCAN_INTERVAL: Final = 60
DEFAULT_CLIENT_NAME: Final = "HomeAssistant"

# Supported Platforms
PLATFORMS: Final[list[Platform]] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

# Device Hierarchy Keys
DEV_TYPE_GATEWAY: Final = "gateway"
DEV_TYPE_HEAT_SOURCE: Final = "heat_source"
DEV_TYPE_HEATING_CIRCUIT: Final = "heating_circuit"
DEV_TYPE_DHW_CIRCUIT: Final = "dhw_circuit"
DEV_TYPE_SOLAR_CIRCUIT: Final = "solar_circuit"
DEV_TYPE_VENTILATION: Final = "ventilation"
DEV_TYPE_ZONE: Final = "zone"
DEV_TYPE_DEVICE: Final = "device"
DEV_TYPE_POOL: Final = "pool"

# Known Circuit / Component ID limits
CANDIDATE_HEATING_CIRCUITS: Final = ("hc1", "hc2", "hc3", "hc4")
CANDIDATE_DHW_CIRCUITS: Final = ("dhw1", "dhw2")
CANDIDATE_HEAT_SOURCES: Final = ("hs1", "hs2", "hs3", "hs4", "hs5", "hs6")
CANDIDATE_SOLAR_CIRCUITS: Final = ("sc1",)
CANDIDATE_VENTILATION_ZONES: Final = ("zone1",)
CANDIDATE_ZONES: Final = tuple(f"zone{i}" for i in range(1, 17))
CANDIDATE_DEVICES: Final = tuple(f"device{i}" for i in range(1, 33))
