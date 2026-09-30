"""Data models and entity descriptions for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
import re
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CANDIDATE_DEVICES,
    CANDIDATE_DHW_CIRCUITS,
    CANDIDATE_HEAT_SOURCES,
    CANDIDATE_HEATING_CIRCUITS,
    CANDIDATE_SOLAR_CIRCUITS,
    CANDIDATE_VENTILATION_ZONES,
    CANDIDATE_ZONES,
    DEV_TYPE_DEVICE,
    DEV_TYPE_DHW_CIRCUIT,
    DEV_TYPE_GATEWAY,
    DEV_TYPE_HEAT_SOURCE,
    DEV_TYPE_HEATING_CIRCUIT,
    DEV_TYPE_POOL,
    DEV_TYPE_SOLAR_CIRCUIT,
    DEV_TYPE_VENTILATION,
    DEV_TYPE_ZONE,
)


def clean_entity_name(name: str | None) -> str | None:
    """Strip redundant device names from entity names so Home Assistant does not duplicate them."""
    if not name:
        return name
    # Prefixes to strip
    prefixes = (
        "HybridManager ",
        "Kessel ",
        "Heizkreis 1 ",
        "Heizkreis 2 ",
        "Warmwasser 1 ",
        "Warmwasser 2 ",
        "Solarkreis 1 ",
        "Solarkreis 2 ",
        "Wärmepumpe ",
    )
    for p in prefixes:
        if name.startswith(p):
            name = name[len(p):]

    # Suffixes to strip
    suffixes = (
        " HybridManager",
        " Kessel",
        " Wärmepumpe",
        " Heizkreis 1",
        " Heizkreis 2",
        " Warmwasser 1",
        " Warmwasser 2",
        " Solarkreis 1",
        " Solarkreis 2",
        " HS1",
        " hs1",
        " HS2",
        " hs2",
    )
    for s in suffixes:
        if name.endswith(s):
            name = name[:-len(s)]

    return name.strip()


def decode_bosch_name(raw_val: Any) -> str | None:
    """Decode Bosch base64 utf-16be encoded string or return clean string."""
    if raw_val is None:
        return None
    val_str = str(raw_val).strip()
    if not val_str:
        return None
    try:
        decoded_bytes = base64.b64decode(val_str, validate=True)
        decoded = decoded_bytes.decode("utf-16be").strip("\x00 \t\n\r")
        if decoded:
            return decoded
    except Exception:
        pass
    return val_str


def sanitize_serial_number(raw_val: Any) -> str | None:
    """Validate and clean serial number string.

    Strips trailing padding/replacement characters (e.g. 0xFF -> \ufffd) and
    rejects corrupted binary memory dumps or strings containing control characters.
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, float):
        try:
            val_str = str(int(raw_val))
        except (ValueError, OverflowError):
            val_str = str(raw_val).strip()
    else:
        val_str = str(raw_val).strip()

    if not val_str or val_str.lower() in ("none", "null", "unknown", "unavailable", "0"):
        return None

    # Strip trailing nulls, unicode replacement characters (\ufffd), or 0xFF padding
    val_clean = val_str.rstrip("\x00\ufffd \t\r\n\x1a\xff")

    # If any control characters (0..31, 127) or replacement characters remain, reject corrupted data
    if any(ord(c) < 32 or ord(c) == 127 or c == "\ufffd" for c in val_clean):
        return None

    # Bosch/Buderus serial numbers are 6..40 alphanumeric chars (plus optional hyphens or periods)
    if not re.fullmatch(r"[A-Za-z0-9\-\.]{6,40}", val_clean):
        return None

    # Must contain at least 5 digits
    if sum(1 for c in val_clean if c.isdigit()) < 5:
        return None

    return val_clean


def parse_notifications(raw_val: Any) -> str | int:
    """Parse notifications list or count."""
    if not raw_val:
        return "Keine"
    if isinstance(raw_val, list):
        if len(raw_val) == 0:
            return "Keine"
        if len(raw_val) == 1 and isinstance(raw_val[0], dict):
            dcd = raw_val[0].get("dcd", "")
            ccd = raw_val[0].get("ccd", "")
            return f"{dcd} ({ccd})"
        return f"{len(raw_val)} aktiv"
    return str(raw_val)


def parse_appliance_name(raw_val: Any) -> str | None:
    """Extract primary appliance product name from basicInfo."""
    modules = raw_val.get("values") if isinstance(raw_val, dict) else raw_val
    if isinstance(modules, list):
        for m in modules:
            if isinstance(m, dict) and m.get("ProductName"):
                return m["ProductName"]
    return None


def parse_update_status(raw_val: Any) -> str | None:
    """Extract clean status string from complex update status object."""
    if isinstance(raw_val, dict):
        status = raw_val.get("status")
        if isinstance(status, dict):
            return status.get("value")
        if status:
            return str(status)
    return str(raw_val) if raw_val is not None else None


def parse_device_errors(raw_val: Any) -> str | None:
    """Extract clean error string from device errors list."""
    if isinstance(raw_val, dict):
        values = raw_val.get("values")
        if isinstance(values, list):
            active_errors = []
            for item in values:
                if isinstance(item, dict):
                    err_type = item.get("errorType", "")
                    val = item.get("value", "")
                    if val and val not in ("inactive", "noError", "valveTight"):
                        active_errors.append(f"{err_type}: {val}")
            if active_errors:
                return ", ".join(active_errors)[:255]
            return "Keine Fehler"
        return "Keine Fehler"
    elif isinstance(raw_val, list):
        if len(raw_val) == 0:
            return "Keine Fehler"
        return f"{len(raw_val)} Fehler"
    return str(raw_val) if raw_val is not None else None


def parse_smart_grid_mode(raw_val: Any) -> str | None:
    """Format Smart Grid Mode (0..3) to human-readable description."""
    if raw_val is None:
        return None
    if isinstance(raw_val, dict):
        raw_val = raw_val.get("value", raw_val)
    modes = {
        0: "Mode 1 (Blocked)",
        1: "Mode 2 (Normal)",
        2: "Mode 3 (Preferred)",
        3: "Mode 4 (Forced)",
    }
    try:
        idx = int(raw_val)
        return modes.get(idx, f"Mode {idx}")
    except (ValueError, TypeError):
        val_str = str(raw_val).strip()
        for k, v in modes.items():
            if val_str.lower() in (str(k), v.lower()):
                return v
        return val_str


def parse_active_heat_source(raw_val: Any) -> str:
    """Format active heat source to clean human-readable German description."""
    if isinstance(raw_val, dict):
        raw_val = raw_val.get("value", raw_val)
    if not raw_val:
        return "Keiner (Standby)"
    val_str = str(raw_val).strip().lower()
    mapping = {
        "none": "Keiner (Standby)",
        "heatpump_only": "Wärmepumpe",
        "boiler_only": "Kessel",
        "parallel": "Parallelbetrieb (WP + Kessel)",
        "unknown": "Wird ermittelt",
        "off": "Aus",
    }
    return mapping.get(val_str, str(raw_val).replace("_", " ").title())


def parse_compressor_timer(raw_val: Any) -> int | float:
    """Format compressor timer (minutes), defaulting to 0 when inactive."""
    if isinstance(raw_val, dict):
        raw_val = raw_val.get("value", raw_val)
    if raw_val is None:
        return 0
    try:
        f_val = float(raw_val)
        return int(f_val) if f_val.is_integer() else f_val
    except (ValueError, TypeError):
        return 0


@dataclass(frozen=True, kw_only=True)
class BoschK40SensorEntityDescription(SensorEntityDescription):
    """Class describing Bosch K40 sensor entity."""

    resource_id: str
    target_device_type: str
    device_sub_id: str | None = None
    device_name: str | None = None
    value_key: str | None = None
    value_fn: Callable[[Any], Any] | None = None
    coordinator_fn: Callable[[Any], Any] | None = None


def parse_installation_date(coordinator: Any) -> date | None:
    """Parse combined installation date from SC day, month, year signals."""
    day_val = coordinator.get_value("/signals/SC.InstallationDate.Day")
    month_val = coordinator.get_value("/signals/SC.InstallationDate.Month")
    year_val = coordinator.get_value("/signals/SC.InstallationDate.Year")
    if day_val is None or month_val is None or year_val is None:
        return None
    try:
        day = int(day_val)
        month = int(month_val)
        year = int(year_val)
        if year < 100:
            year += 2000
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True, kw_only=True)
class BoschK40BinarySensorEntityDescription(BinarySensorEntityDescription):
    """Class describing Bosch K40 binary sensor entity."""

    resource_id: str
    target_device_type: str
    device_sub_id: str | None = None
    device_name: str | None = None
    on_values: tuple[Any, ...] = (
        "on",
        "active",
        "yes",
        "ONLINE",
        "PAIRED",
        "SUPPORTED",
        "SUCCESS",
        "ch_enabled",
        "dhw_enabled",
        1,
        True,
    )


# ---------------------------------------------------------------------------
# SENSOR REGISTRY
# ---------------------------------------------------------------------------

def build_gateway_sensors() -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for the Parent Gateway device."""
    return [
        BoschK40SensorEntityDescription(
            key="gateway_brand",
            resource_id="/gateway/brand",
            name="Marke",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_firmware",
            resource_id="/gateway/versionFirmware",
            name="Firmware-Version",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cellphone-arrow-down",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_hardware",
            resource_id="/gateway/versionHardware",
            name="Hardware-Version",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:chip",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_eth_mac",
            resource_id="/gateway/eth/mac",
            name="Ethernet MAC",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ethernet",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_wifi_mac",
            resource_id="/gateway/wifi/mac",
            name="WLAN MAC",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_eth_ip",
            resource_id="/gateway/eth/ip/ipv4",
            name="Ethernet IP",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ip-network",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_wifi_ip",
            resource_id="/gateway/wifi/ip/ipv4",
            name="WLAN IP",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:ip-network-outline",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_wifi_ssid",
            resource_id="/gateway/wifi/ssid",
            name="WLAN SSID",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi-cog",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_data_processing",
            resource_id="/gateway/dataProcessing/status",
            name="Datenverarbeitung Status",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cloud-sync",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_timezone",
            resource_id="/gateway/tzInfo/timeZone",
            name="Zeitzone",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:map-clock",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_hotspot_remaining",
            resource_id="/gateway/wifi/hotspotRemainingTime",
            name="Hotspot Restzeit",
            target_device_type=DEV_TYPE_GATEWAY,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:timer-outline",
        ),
        BoschK40SensorEntityDescription(
            key="system_bus",
            resource_id="/system/bus",
            name="Bus-System",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cable-data",
        ),
        BoschK40SensorEntityDescription(
            key="system_type",
            resource_id="/system/type",
            name="Systemtyp",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cog",
        ),
        BoschK40SensorEntityDescription(
            key="system_notifications",
            resource_id="/notifications",
            name="Systemmeldungen / Störungen",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=parse_notifications,
            icon="mdi:alert-circle-outline",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_update_status",
            resource_id="/gateway/update/status",
            name="Gateway Update Status",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=parse_update_status,
            icon="mdi:update",
        ),
        BoschK40SensorEntityDescription(
            key="system_update_status",
            resource_id="/system/update/status",
            name="System Update Status",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=parse_update_status,
            icon="mdi:update",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_update_report",
            resource_id="/gateway/update/report",
            name="Gateway Update Bericht",
            target_device_type=DEV_TYPE_GATEWAY,
            value_fn=parse_update_status,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:update",
        ),
        BoschK40SensorEntityDescription(
            key="gateway_wifi_pairing_status",
            resource_id="/gateway/wifi/pairingStatus",
            name="WLAN Pairing Status",
            target_device_type=DEV_TYPE_GATEWAY,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi-settings",
        ),
    ]


def build_heat_source_global_sensors() -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for central heat source / Wärmepumpe."""
    return [
        BoschK40SensorEntityDescription(
            key="sc_installation_date",
            resource_id="/signals/SC.InstallationDate",
            name="Installationsdatum",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id="hybman",
            device_name="HybridManager",
            device_class=SensorDeviceClass.DATE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:calendar-check",
            coordinator_fn=parse_installation_date,
        ),
        BoschK40SensorEntityDescription(
            key="smart_grid_mode",
            resource_id="/signals/HYBMAN.SmartGridMode",
            name="Smart Grid Modus",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id="hybman",
            device_name="HybridManager",
            icon="mdi:transmission-tower",
            value_fn=parse_smart_grid_mode,
        ),
        BoschK40SensorEntityDescription(
            key="hybman_time_till_next_compressor_start",
            resource_id="/signals/HYBMAN.TimeTillNextCompressorStart",
            name="Restzeit bis Verdichterstart",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id="hybman",
            device_name="HybridManager",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-sand",
            value_fn=parse_compressor_timer,
        ),
        BoschK40SensorEntityDescription(
            key="hybman_time_till_next_compressor_stop",
            resource_id="/signals/HYBMAN.TimeTillNextCompressorStop",
            name="Restzeit bis Verdichterstopp",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id="hybman",
            device_name="HybridManager",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-sand-complete",
            value_fn=parse_compressor_timer,
        ),
        BoschK40SensorEntityDescription(
            key="outdoor_temperature",
            resource_id="/system/sensors/temperatures/outdoor_t1",
            name="Außentemperatur",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key="actual_supply_temperature",
            resource_id="/heatSources/actualSupplyTemperature",
            name="Vorlauftemperatur Ist",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key="current_supply_setpoint",
            resource_id="/heatSources/currentSupplySetpoint",
            name="Vorlauftemperatur Soll",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-lines",
        ),
        BoschK40SensorEntityDescription(
            key="return_temperature",
            resource_id="/heatSources/returnTemperature",
            name="Rücklauftemperatur",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key="system_pressure",
            resource_id="/heatSources/systemPressure",
            name="Systemdruck",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPressure.BAR,
            icon="mdi:gauge",
        ),
        BoschK40SensorEntityDescription(
            key="actual_modulation",
            resource_id="/heatSources/actualModulation",
            name="Modulation",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:speedometer",
        ),
        BoschK40SensorEntityDescription(
            key="actual_heat_demand",
            resource_id="/heatSources/actualHeatDemand",
            name="Wärmebedarf",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:fire",
        ),
        BoschK40SensorEntityDescription(
            key="number_of_starts",
            resource_id="/heatSources/numberOfStarts",
            name="Brenner- / Verdichterstarts Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:counter",
        ),
        BoschK40SensorEntityDescription(
            key="refrigerant_circuits_online",
            resource_id="/heatSources/numberOfRefrigerantCircuitsOnline",
            name="Kältekreise online",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:numeric",
        ),
        BoschK40SensorEntityDescription(
            key="hybrid_active_heat_source",
            resource_id="/heatSources/hybrid/activeHeatSource",
            name="Aktiver Wärmeerzeuger",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id="hybman",
            device_name="HybridManager",
            icon="mdi:swap-horizontal-bold",
            value_fn=parse_active_heat_source,
        ),
        BoschK40SensorEntityDescription(
            key="evaporator_temp_tl1",
            resource_id="/heatSources/sensors/evaporatorTemp_tl1",
            name="Verdampfertemperatur TL1",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:snowflake-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key="evaporator_temp_tl2",
            resource_id="/heatSources/sensors/evaporatorTemp_tl2",
            name="Verdampfertemperatur TL2",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:snowflake-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key="cylinder_temperature",
            resource_id="/heatSources/dhw/cylinderTemperature",
            name="Warmwasserspeicher Temperatur",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key="cylinder_upper_temp",
            resource_id="/heatSources/dhw/cylinderUpperTemp",
            name="Warmwasserspeicher Temperatur oben",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:water-boiler-outline",
        ),
        BoschK40SensorEntityDescription(
            key="additional_heater_flow_temp",
            resource_id="/heatSources/additionalHeater/flowTemp",
            name="Zuheizer Vorlauftemperatur",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-plus",
        ),
        BoschK40SensorEntityDescription(
            key="compressor_power_actual",
            resource_id="/heatSources/compressor/powerElecActual",
            name="Verdichter elektrische Leistung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            icon="mdi:lightning-bolt",
        ),
        BoschK40SensorEntityDescription(
            key="eheater_power_actual",
            resource_id="/heatSources/eHeater/powerElecActual",
            name="Elektroheizer Leistung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key="eheater_power_actual_low_res",
            resource_id="/heatSources/eHeater/powerElecActualLowResolution",
            name="Elektroheizer Leistung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key="working_time_total_system",
            resource_id="/heatSources/workingTime/totalSystem",
            name="Betriebszeit Gesamtsystem",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfTime.SECONDS,
            icon="mdi:clock-outline",
        ),
        # -------------------------------------------------------------------
        # ENERGY MONITORING (emon) - Alle Teil-Metriken vollständig aufgeschlüsselt!
        # -------------------------------------------------------------------
        # Gesamt
        BoschK40SensorEntityDescription(
            key="emon_total_output",
            resource_id="/heatSources/emon/totalConsumption",
            name="Erzeugte Wärmeenergie Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:fire-circle",
        ),
        BoschK40SensorEntityDescription(
            key="emon_total_burner",
            resource_id="/heatSources/emon/totalConsumption",
            name="Brennerenergie Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="burner",
            icon="mdi:gas-burner",
        ),
        BoschK40SensorEntityDescription(
            key="emon_total_solar",
            resource_id="/heatSources/emon/totalConsumption",
            name="Solarenergie Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="solar",
            icon="mdi:solar-power",
        ),
        BoschK40SensorEntityDescription(
            key="emon_total_electricity",
            resource_id="/heatSources/emon/totalConsumption",
            name="Stromverbrauch Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="electricity",
            icon="mdi:meter-electric",
        ),
        BoschK40SensorEntityDescription(
            key="emon_total_eheater",
            resource_id="/heatSources/emon/totalConsumption",
            name="Zuheizer Energie Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="eheater",
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key="emon_total_compressor",
            resource_id="/heatSources/emon/totalConsumption",
            name="Verdichter Energie Gesamt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="compressor",
            icon="mdi:heat-pump",
        ),
        # Heizung (ch)
        BoschK40SensorEntityDescription(
            key="emon_ch_output",
            resource_id="/heatSources/emon/chConsumption",
            name="Erzeugte Wärmeenergie Heizung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key="emon_ch_burner",
            resource_id="/heatSources/emon/chConsumption",
            name="Brennerenergie Heizung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="burner",
            icon="mdi:gas-burner",
        ),
        BoschK40SensorEntityDescription(
            key="emon_ch_electricity",
            resource_id="/heatSources/emon/chConsumption",
            name="Stromverbrauch Heizung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="electricity",
            icon="mdi:meter-electric",
        ),
        BoschK40SensorEntityDescription(
            key="emon_ch_eheater",
            resource_id="/heatSources/emon/chConsumption",
            name="Zuheizer Energie Heizung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="eheater",
            icon="mdi:heating-coil",
        ),
        # Warmwasser (dhw)
        BoschK40SensorEntityDescription(
            key="emon_dhw_output",
            resource_id="/heatSources/emon/dhwConsumption",
            name="Erzeugte Wärmeenergie Warmwasser",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key="emon_dhw_burner",
            resource_id="/heatSources/emon/dhwConsumption",
            name="Brennerenergie Warmwasser",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="burner",
            icon="mdi:gas-burner",
        ),
        BoschK40SensorEntityDescription(
            key="emon_dhw_electricity",
            resource_id="/heatSources/emon/dhwConsumption",
            name="Stromverbrauch Warmwasser",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="electricity",
            icon="mdi:meter-electric",
        ),
        BoschK40SensorEntityDescription(
            key="emon_dhw_eheater",
            resource_id="/heatSources/emon/dhwConsumption",
            name="Zuheizer Energie Warmwasser",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="eheater",
            icon="mdi:heating-coil",
        ),
        # Kühlung
        BoschK40SensorEntityDescription(
            key="emon_cooling_output",
            resource_id="/heatSources/emon/coolingConsumption",
            name="Kälteenergie Erzeugt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:snowflake",
        ),
        BoschK40SensorEntityDescription(
            key="emon_cooling_electricity",
            resource_id="/heatSources/emon/coolingConsumption",
            name="Stromverbrauch Kühlung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="compressor",
            icon="mdi:meter-electric",
        ),
        # Pool
        BoschK40SensorEntityDescription(
            key="emon_pool_output",
            resource_id="/heatSources/emon/poolConsumption",
            name="Wärmeenergie Pool",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:pool",
        ),
        # Variable tariff
        BoschK40SensorEntityDescription(
            key="tariff_ch_setpoint",
            resource_id="/system/variableTariff/ch/currentSetpoint",
            name="Variabler Tarif Heizung Sollwert",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:cash-clock",
        ),
        BoschK40SensorEntityDescription(
            key="tariff_price_categorization",
            resource_id="/system/variableTariff/currentPriceCatagorization",
            name="Variabler Tarif Preiskategorie",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:tag-outline",
        ),
        BoschK40SensorEntityDescription(
            key="tariff_id",
            resource_id="/system/variableTariff/tariffId",
            name="Tarif-ID",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:identifier",
        ),
        BoschK40SensorEntityDescription(
            key="heat_sources_em_status",
            resource_id="/heatSources/emStatus",
            name="Energiemanager Status",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:lightning-bolt",
        ),
        # Variable Tariff
        BoschK40SensorEntityDescription(
            key="variable_tariff_support_status",
            resource_id="/system/variableTariff/supportStatus",
            name="Variabler Tarif Support",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:currency-eur",
        ),
        BoschK40SensorEntityDescription(
            key="variable_tariff_ch_status",
            resource_id="/system/variableTariff/ch/status",
            name="Variabler Tarif Heizung Status",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:tag-outline",
        ),
        BoschK40SensorEntityDescription(
            key="variable_tariff_dhw_status",
            resource_id="/system/variableTariff/dhw/status",
            name="Variabler Tarif Warmwasser Status",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:tag-outline",
        ),
        BoschK40SensorEntityDescription(
            key="variable_tariff_dhw_current_opmode",
            resource_id="/system/variableTariff/dhw/currentOpmode",
            name="Variabler Tarif Warmwasser Betriebsart",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cog",
        ),
        BoschK40SensorEntityDescription(
            key="variable_tariff_ch_high_price_delta",
            resource_id="/system/variableTariff/ch/highPriceDelta",
            name="Variabler Tarif Heizung Hochpreis Delta",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key="variable_tariff_ch_low_price_delta",
            resource_id="/system/variableTariff/ch/lowPriceDelta",
            name="Variabler Tarif Heizung Niedrigpreis Delta",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key="variable_tariff_ch_mid_price_setpoint",
            resource_id="/system/variableTariff/ch/midPriceSetpoint",
            name="Variabler Tarif Heizung Normalpreis Sollwert",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key="devices_inclusion_time",
            resource_id="/devices/inclusionTime",
            name="Geräte Anlernzeit",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.SECONDS,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:timer-sand",
        ),
        BoschK40SensorEntityDescription(
            key="devices_rhc_assigned",
            resource_id="/devices/rhc/assignedTo",
            name="Raumthermostat Heizkreis Zuordnung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key="devices_uhc_assigned",
            resource_id="/devices/uhc/assignedTo",
            name="Fußbodenheizung Heizkreis Zuordnung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key="zones_configuration_max",
            resource_id="/zones/configuration",
            name="Maximal unterstützte Zonen",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda x: x.get("values", {}).get("maxSupportedZones", [{}])[1].get("value") if isinstance(x, dict) and len(x.get("values", {}).get("maxSupportedZones", [])) > 1 else None,
            icon="mdi:home-group",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_additional_heater_ch",
            resource_id="/system/powerConstraints/affectedDomain/additionalHeaterCh",
            name="Leistungsbegrenzung Zuheizer Heizung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_additional_heater_dhw_tank",
            resource_id="/system/powerConstraints/affectedDomain/additionalHeaterDhwTank",
            name="Leistungsbegrenzung Zuheizer Warmwasserspeicher",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_additional_heater_pri",
            resource_id="/system/powerConstraints/affectedDomain/additionalHeaterPrimaryCircuit",
            name="Leistungsbegrenzung Zuheizer Primärkreis",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_ch",
            resource_id="/system/powerConstraints/affectedDomain/ch",
            name="Leistungsbegrenzung Heizung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_cooling",
            resource_id="/system/powerConstraints/affectedDomain/cooling",
            name="Leistungsbegrenzung Kühlung",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:snowflake",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_dhw",
            resource_id="/system/powerConstraints/affectedDomain/dhw",
            name="Leistungsbegrenzung Warmwasser",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_pool",
            resource_id="/system/powerConstraints/affectedDomain/pool",
            name="Leistungsbegrenzung Pool",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:pool",
        ),
        BoschK40SensorEntityDescription(
            key="pc_aff_refrigerant_circuit",
            resource_id="/system/powerConstraints/affectedDomain/refrigerantCircuit",
            name="Leistungsbegrenzung Kältekreis",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:heat-pump",
        ),
    ]


def build_heat_source_unit_sensors(hs_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for a specific heat source unit (hs1..hs6)."""
    sub_title = hs_id.upper()
    return [
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_heat_pump_type",
            resource_id=f"/heatSources/{hs_id}/heatPumpType",
            name=f"Wärmepumpentyp {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            icon="mdi:heat-pump",
        ),
        # Starts Aufteilung (ch, dhw, total)
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_starts_total",
            resource_id=f"/heatSources/{hs_id}/numberOfStarts",
            name=f"Starts Gesamt {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            value_key="total",
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:counter",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_starts_ch",
            resource_id=f"/heatSources/{hs_id}/numberOfStarts",
            name=f"Starts Heizung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            value_key="ch",
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_starts_dhw",
            resource_id=f"/heatSources/{hs_id}/numberOfStarts",
            name=f"Starts Warmwasser {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            value_key="dhw",
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:water-boiler",
        ),
        # Working time
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_working_time_total",
            resource_id=f"/heatSources/{hs_id}/workingTime",
            name=f"Betriebszeit Gesamt {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            value_key="total",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.HOURS,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:clock-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_working_time_ch",
            resource_id=f"/heatSources/{hs_id}/workingTime",
            name=f"Betriebszeit Heizung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            value_key="ch",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.HOURS,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_working_time_dhw",
            resource_id=f"/heatSources/{hs_id}/workingTime",
            name=f"Betriebszeit Warmwasser {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            value_key="dhw",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.HOURS,
            state_class=SensorStateClass.TOTAL_INCREASING,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_odu_fan_speed",
            resource_id=f"/heatSources/{hs_id}/oduFanSpeed",
            name=f"Lüfterdrehzahl Außeneinheit {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:fan",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_pump_volume_flow",
            resource_id=f"/heatSources/{hs_id}/pumpVolumeFlow",
            name=f"Pumpendurchfluss {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="L/h",
            icon="mdi:water-pump",
            value_fn=lambda val: (val * 10) if isinstance(val, (int, float)) else val,
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_return_flow_temp",
            resource_id=f"/heatSources/{hs_id}/returnFlowTemp",
            name=f"Rücklauftemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_supply_flow_condenser_temp",
            resource_id=f"/heatSources/{hs_id}/supplyFlowCondenserTemp",
            name=f"Kondensator Vorlauftemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_compressor_actual_speed",
            resource_id=f"/heatSources/{hs_id}/refrigerant/compressorActualSpeed",
            name=f"Verdichter Drehzahl {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:speedometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_compressor_power_actual",
            resource_id=f"/heatSources/{hs_id}/refrigerant/compressorElecPowerActual",
            name=f"Verdichter Leistung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPower.WATT,
            icon="mdi:lightning-bolt",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_compressor_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/compressorTemp",
            name=f"Verdichtertemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_heat_carrier_pump_speed",
            resource_id=f"/heatSources/{hs_id}/refrigerant/heatCarrierPumpSpeed",
            name=f"Wärmeträgerpumpe Drehzahl {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:pump",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_high_pressure_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/highPressureTemp",
            name=f"Hochdrucktemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-high",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_hot_gas_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/hotGasTemp",
            name=f"Heißgastemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:fire-alert",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_liquid_pipe_cooling_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/liquidPipeCoolingTemp",
            name=f"Flüssigkeitsleitung Kühlung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-snowflake",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_liquid_pipe_heating_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/liquidPipeHeatingTemp",
            name=f"Flüssigkeitsleitung Heizung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_low_pressure_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/lowPressureTemp",
            name=f"Niederdrucktemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-low",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_refrigerant_status",
            resource_id=f"/heatSources/{hs_id}/refrigerant/status",
            name=f"Kältekreis Status {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            icon="mdi:information-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_suction_gas_temp",
            resource_id=f"/heatSources/{hs_id}/refrigerant/suctionGasTemp",
            name=f"Sauggastemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_safety_board_status",
            resource_id=f"/heatSources/{hs_id}/safetyBoard/status",
            name=f"Sicherheitsplatine Status {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            icon="mdi:shield-check-outline",
        ),
        # Brine circuit (Erdwärme / Sole)
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_brine_collector_inflow",
            resource_id=f"/heatSources/{hs_id}/brineCircuit/collectorInflowTemp",
            name=f"Solekreis Zulauftemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_brine_collector_outflow",
            resource_id=f"/heatSources/{hs_id}/brineCircuit/collectorOutflowTemp",
            name=f"Solekreis Ablauftemperatur {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_brine_pressure",
            resource_id=f"/heatSources/{hs_id}/brineCircuit/pressure",
            name=f"Soledruck {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPressure.BAR,
            icon="mdi:gauge",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_brine_pump_speed",
            resource_id=f"/heatSources/{hs_id}/brineCircuit/pumpSpeed",
            name=f"Solepumpe Drehzahl {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:pump",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_brine_volume_flow",
            resource_id=f"/heatSources/{hs_id}/brineCircuit/volumeFlow",
            name=f"Sole Durchfluss {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="L/h",
            icon="mdi:water-pump",
            value_fn=lambda val: (val * 10) if isinstance(val, (int, float)) else val,
        ),
        # Unit-specific emon sensors
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_emon_total_output",
            resource_id=f"/heatSources/{hs_id}/emon/totalConsumption",
            name=f"Erzeugte Wärmeenergie Gesamt {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:fire-circle",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_emon_total_compressor",
            resource_id=f"/heatSources/{hs_id}/emon/totalConsumption",
            name=f"Verdichter Energie Gesamt {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="compressor",
            icon="mdi:heat-pump",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_emon_ch_output",
            resource_id=f"/heatSources/{hs_id}/emon/chConsumption",
            name=f"Erzeugte Wärmeenergie Heizung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_emon_ch_compressor",
            resource_id=f"/heatSources/{hs_id}/emon/chConsumption",
            name=f"Verdichter Energie Heizung {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="compressor",
            icon="mdi:heat-pump",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_emon_dhw_output",
            resource_id=f"/heatSources/{hs_id}/emon/dhwConsumption",
            name=f"Erzeugte Wärmeenergie Warmwasser {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="outputProduced",
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hs_id}_emon_dhw_compressor",
            resource_id=f"/heatSources/{hs_id}/emon/dhwConsumption",
            name=f"Verdichter Energie Warmwasser {sub_title}",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_sub_id=hs_id,
            device_name=f"Wärmeerzeuger {sub_title}",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            value_key="compressor",
            icon="mdi:heat-pump",
        ),
    ]


def build_heating_circuit_sensors(hc_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for heating circuit (hc1..hc4)."""
    num = hc_id.replace("hc", "")
    dev_name = f"Heizkreis {num}"
    return [
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_room_temperature",
            resource_id=f"/heatingCircuits/{hc_id}/roomtemperature",
            name=f"Raumtemperatur {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:home-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_current_room_setpoint",
            resource_id=f"/heatingCircuits/{hc_id}/currentRoomSetpoint",
            name=f"Raumtemperatur Soll {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:home-thermometer-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_actual_humidity",
            resource_id=f"/heatingCircuits/{hc_id}/actualHumidity",
            name=f"Luftfeuchtigkeit {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:water-percent",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_max_flow_temp",
            resource_id=f"/heatingCircuits/{hc_id}/maxFlowTemp",
            name=f"Maximale Vorlauftemperatur {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-high",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_mixer_position",
            resource_id=f"/heatingCircuits/{hc_id}/mixerPosition",
            name=f"Mischerposition {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:valve",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_current_su_wi_mode",
            resource_id=f"/heatingCircuits/{hc_id}/currentSuWiMode",
            name=f"Sommer-/Winterbetrieb {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            icon="mdi:weather-sunny-alert",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_overall_status",
            resource_id=f"/heatingCircuits/{hc_id}/overallStatus",
            name=f"Status {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key=f"{hc_id}_boost_remaining_time",
            resource_id=f"/heatingCircuits/{hc_id}/boostRemainingTime",
            name=f"Boost Restzeit {dev_name}",
            target_device_type=DEV_TYPE_HEATING_CIRCUIT,
            device_sub_id=hc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-sand",
        ),
    ]


def build_dhw_circuit_sensors(dhw_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for DHW circuit (dhw1..dhw2)."""
    num = dhw_id.replace("dhw", "")
    dev_name = f"Warmwasser {num}"
    return [
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_actual_temp",
            resource_id=f"/dhwCircuits/{dhw_id}/actualTemp",
            name=f"Warmwassertemperatur Ist {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:water-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_current_setpoint",
            resource_id=f"/dhwCircuits/{dhw_id}/currentSetpoint",
            name=f"Warmwassertemperatur Soll {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-lines",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_out_temp",
            resource_id=f"/dhwCircuits/{dhw_id}/outTemp",
            name=f"Auslauftemperatur {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_current_friwa_supply_temp",
            resource_id=f"/dhwCircuits/{dhw_id}/currentFriwaSupplyTemperature",
            name=f"Frischwasser Vorlauf {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_friwa_primary_pump_modulation",
            resource_id=f"/dhwCircuits/{dhw_id}/friwaPrimaryPumpModulation",
            name=f"Frischwasser Primärpumpe Modulation {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:pump",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_volume_flow",
            resource_id=f"/dhwCircuits/{dhw_id}/volumeFlow",
            name=f"Durchflussmenge {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="L/min",
            icon="mdi:waves",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_current_temperature_level",
            resource_id=f"/dhwCircuits/{dhw_id}/currentTemperatureLevel",
            name=f"Temperaturniveau {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            icon="mdi:thermometer-alert",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_overall_status",
            resource_id=f"/dhwCircuits/{dhw_id}/overallStatus",
            name=f"Status {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            icon="mdi:water-boiler",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dhw_id}_charge_remaining_time",
            resource_id=f"/dhwCircuits/{dhw_id}/chargeRemainingTime",
            name=f"Lade-Restzeit {dev_name}",
            target_device_type=DEV_TYPE_DHW_CIRCUIT,
            device_sub_id=dhw_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:timer-outline",
        ),
    ]


def build_solar_circuit_sensors(sc_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for solar circuits (sc1)."""
    num = sc_id.replace("sc", "")
    dev_name = f"Solarkreis {num}"
    return [
        BoschK40SensorEntityDescription(
            key=f"{sc_id}_collector_temp",
            resource_id=f"/solarCircuits/{sc_id}/collectorTemperature",
            name=f"Kollektortemperatur {dev_name}",
            target_device_type=DEV_TYPE_SOLAR_CIRCUIT,
            device_sub_id=sc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:solar-power",
        ),
        BoschK40SensorEntityDescription(
            key=f"{sc_id}_dhw_tank_bottom_temp",
            resource_id=f"/solarCircuits/{sc_id}/dhwTankBottomTemperature",
            name=f"Solarspeicher Temperatur unten {dev_name}",
            target_device_type=DEV_TYPE_SOLAR_CIRCUIT,
            device_sub_id=sc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key=f"{sc_id}_pump_modulation",
            resource_id=f"/solarCircuits/{sc_id}/pumpModulation",
            name=f"Solarpumpe Modulation {dev_name}",
            target_device_type=DEV_TYPE_SOLAR_CIRCUIT,
            device_sub_id=sc_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:pump",
        ),
        BoschK40SensorEntityDescription(
            key=f"{sc_id}_solar_yield",
            resource_id=f"/solarCircuits/{sc_id}/solarYield",
            name=f"Solarertrag {dev_name}",
            target_device_type=DEV_TYPE_SOLAR_CIRCUIT,
            device_sub_id=sc_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
            icon="mdi:solar-power-variant",
        ),
    ]


def build_ventilation_sensors(vz_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for ventilation (zone1)."""
    dev_name = f"Lüftung {vz_id}"
    return [
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_outdoor_temp",
            resource_id=f"/ventilation/{vz_id}/sensors/outdoorTemp",
            name=f"Außentemperatur {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_supply_temp",
            resource_id=f"/ventilation/{vz_id}/sensors/supplyTemp",
            name=f"Zulufttemperatur {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_extract_temp",
            resource_id=f"/ventilation/{vz_id}/sensors/extractTemp",
            name=f"Ablufttemperatur {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-down",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_exhaust_temp",
            resource_id=f"/ventilation/{vz_id}/sensors/exhaustTemp",
            name=f"Fortlufttemperatur {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-minus",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_internal_humidity",
            resource_id=f"/ventilation/{vz_id}/sensors/internalHumidity",
            name=f"Raumluftfeuchtigkeit {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:water-percent",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_external_humidity",
            resource_id=f"/ventilation/{vz_id}/sensors/externalHumidity",
            name=f"Außenluftfeuchtigkeit {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:water-percent",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_internal_air_quality",
            resource_id=f"/ventilation/{vz_id}/sensors/internalAirQuality",
            name=f"Raumluftqualität {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.AQI,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="ppm",
            icon="mdi:air-filter",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_external_air_quality",
            resource_id=f"/ventilation/{vz_id}/sensors/externalAirQuality",
            name=f"Außenluftqualität {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.AQI,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="ppm",
            icon="mdi:air-filter",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_supply_fan_speed",
            resource_id=f"/ventilation/{vz_id}/sensors/supplyFanRotation",
            name=f"Zuluftventilator Drehzahl {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="rpm",
            icon="mdi:fan",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_exhaust_fan_speed",
            resource_id=f"/ventilation/{vz_id}/exhaustFanSpeed",
            name=f"Abluftventilator Drehzahl {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="rpm",
            icon="mdi:fan",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_supply_fan_power",
            resource_id=f"/ventilation/{vz_id}/supplyFanPower",
            name=f"Zuluft Leistung {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:fan",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_exhaust_fan_power",
            resource_id=f"/ventilation/{vz_id}/exhaustFanPower",
            name=f"Abluft Leistung {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:fan",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_exhaust_fan_level",
            resource_id=f"/ventilation/{vz_id}/exhaustFanLevel",
            name=f"Lüfterstufe {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            icon="mdi:fan-speed-1",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_filter_remaining_time",
            resource_id=f"/ventilation/{vz_id}/filter/remainingTime",
            name=f"Filter Restzeit {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:air-filter",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_appliance_run_time",
            resource_id=f"/ventilation/{vz_id}/applianceRunTime",
            name=f"Betriebszeit {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            icon="mdi:clock-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_el_aux_heater_power",
            resource_id=f"/ventilation/{vz_id}/elAuxHeaterPower",
            name=f"Zuheizer Leistung {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_electrical_aux_heater_power",
            resource_id=f"/ventilation/{vz_id}/electricalAuxHeaterPower",
            name=f"Elektrischer Zuheizer Leistung {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:heating-coil",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_max_indoor_air_quality",
            resource_id=f"/ventilation/{vz_id}/maxIndoorAirQuality",
            name=f"Max. Raumluftqualität Grenzwert {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.AQI,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="ppm",
            entity_category=EntityCategory.CONFIG,
            icon="mdi:air-filter",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_max_relative_humidity",
            resource_id=f"/ventilation/{vz_id}/maxRelativeHumidity",
            name=f"Max. Raumluftfeuchtigkeit Grenzwert {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.CONFIG,
            icon="mdi:water-percent",
        ),
        BoschK40SensorEntityDescription(
            key=f"{vz_id}_summer_bypass_flap_power",
            resource_id=f"/ventilation/{vz_id}/summerBypass/flapPower",
            name=f"Sommerbypass Klappenstellung {dev_name}",
            target_device_type=DEV_TYPE_VENTILATION,
            device_sub_id=vz_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:valve",
        ),
    ]


def build_pool_sensor() -> BoschK40SensorEntityDescription:
    """Build sensor description for pool."""
    return BoschK40SensorEntityDescription(
        key="pool_current_temperature",
        resource_id="/pool/currentTemp",
        name="Pooltemperatur",
        target_device_type=DEV_TYPE_POOL,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:pool",
    )


def build_zone_sensors(zone_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for heating zone (zone1..zone16)."""
    num = zone_id.replace("zone", "")
    dev_name = f"Zone {num}"
    return [
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_average_current_temp",
            resource_id=f"/zones/{zone_id}/averageCurrentTemperature",
            name=f"Raumtemperatur {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:home-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_average_actual_humidity",
            resource_id=f"/zones/{zone_id}/averageActualHumidity",
            name=f"Luftfeuchtigkeit {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:water-percent",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_current_room_setpoint",
            resource_id=f"/zones/{zone_id}/currentRoomSetpoint",
            name=f"Raumtemperatur Soll {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:home-thermometer-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_heating_operation_mode",
            resource_id=f"/zones/{zone_id}/heating/operationMode",
            name=f"Heizmodus {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_cooling_operation_mode",
            resource_id=f"/zones/{zone_id}/cooling/operationMode",
            name=f"Kühlmodus {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            icon="mdi:snowflake",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_name",
            resource_id=f"/zones/{zone_id}/name",
            name=f"Zonenname {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            value_fn=decode_bosch_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:tag-text-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_heating_manual_setpoint",
            resource_id=f"/zones/{zone_id}/heating/manualRoomSetpoint",
            name=f"Sollwert Manuell Heizen {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_heating_temp_setpoint",
            resource_id=f"/zones/{zone_id}/heating/temporaryRoomSetpoint",
            name=f"Sollwert Temporär Heizen {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-chevron-up",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_cooling_manual_setpoint",
            resource_id=f"/zones/{zone_id}/cooling/manualRoomSetpoint",
            name=f"Sollwert Manuell Kühlen {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:snowflake-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_cooling_temp_setpoint",
            resource_id=f"/zones/{zone_id}/cooling/temporaryRoomSetpoint",
            name=f"Sollwert Temporär Kühlen {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:snowflake-thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{zone_id}_icon",
            resource_id=f"/zones/{zone_id}/icon",
            name=f"Zonensymbol {dev_name}",
            target_device_type=DEV_TYPE_ZONE,
            device_sub_id=zone_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:home-variant-outline",
        ),
    ]


def build_rf_device_sensors(dev_id: str) -> list[BoschK40SensorEntityDescription]:
    """Build sensor descriptions for RF paired device (device1..device32)."""
    num = dev_id.replace("device", "")
    dev_name = f"Gerät {num}"
    return [
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_room_temperature",
            resource_id=f"/devices/{dev_id}/roomtemperature",
            name=f"Raumtemperatur {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_current_room_setpoint",
            resource_id=f"/devices/{dev_id}/currentRoomSetpoint",
            name=f"Raumtemperatur Soll {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer-lines",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_actual_humidity",
            resource_id=f"/devices/{dev_id}/actualHumidity",
            name=f"Luftfeuchtigkeit {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:water-percent",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_actuator_modulation",
            resource_id=f"/devices/{dev_id}/actuatorModulation",
            name=f"Stellantrieb Modulation {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:valve",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_battery",
            resource_id=f"/devices/{dev_id}/battery",
            name=f"Batterie {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            icon="mdi:battery",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_signal",
            resource_id=f"/devices/{dev_id}/signal",
            name=f"Signalstärke {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:wifi-strength-2",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_signal_icon",
            resource_id=f"/devices/{dev_id}/signalIcon",
            name=f"Signalbewertung {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:signal-variant",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_name",
            resource_id=f"/devices/{dev_id}/name",
            name=f"Modell {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:cellphone-link",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_type",
            resource_id=f"/devices/{dev_id}/type",
            name=f"Typ {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:shape",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_firmware",
            resource_id=f"/devices/{dev_id}/versionFirmware",
            name=f"Firmware {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:chip",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_assigned_hc",
            resource_id=f"/devices/{dev_id}/assignedHC",
            name=f"Zugeordneter Heizkreis {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:radiator",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_actuator_power",
            resource_id=f"/devices/{dev_id}/actuatorPower",
            name=f"Stellantrieb Leistung {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:power",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_operation_mode",
            resource_id=f"/devices/{dev_id}/operationMode",
            name=f"Betriebsmodus {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            icon="mdi:cog",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_rf_error_cause",
            resource_id=f"/devices/{dev_id}/rfErrorCause",
            name=f"Funkfehler Ursache {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:alert-circle-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_rf_time_connection_lost",
            resource_id=f"/devices/{dev_id}/rfTimeofConnectionLost",
            name=f"Verbindungsverlust Zeitstempel {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:clock-alert-outline",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_sgtin",
            resource_id=f"/devices/{dev_id}/sgtin",
            name=f"Seriennummer (SGTIN) {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:barcode",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_zone_id",
            resource_id=f"/devices/{dev_id}/zoneId",
            name=f"Zugeordnete Zone {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:home-group",
        ),
        BoschK40SensorEntityDescription(
            key=f"{dev_id}_errors",
            resource_id=f"/devices/{dev_id}/errors",
            name=f"Gerätefehler {dev_name}",
            target_device_type=DEV_TYPE_DEVICE,
            device_sub_id=dev_id,
            device_name=dev_name,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=parse_device_errors,
            icon="mdi:alert-circle",
        ),
    ]


# ---------------------------------------------------------------------------
# BINARY SENSOR REGISTRY
# ---------------------------------------------------------------------------

def build_binary_sensors() -> list[BoschK40BinarySensorEntityDescription]:
    """Build all known binary sensor descriptions."""
    descriptions: list[BoschK40BinarySensorEntityDescription] = [
        # Heat source / boiler
        BoschK40BinarySensorEntityDescription(
            key="flame_status",
            resource_id="/heatSources/flameStatus",
            name="Flammenstatus",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.RUNNING,
            icon="mdi:fire",
        ),
        BoschK40BinarySensorEntityDescription(
            key="smart_function_active",
            resource_id="/heatSources/smartFunction/active",
            name="Smart-Funktion aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:creation",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pv_contact_state",
            resource_id="/heatSources/pvContactState",
            name="PV-Kontakt",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:solar-power",
        ),
        BoschK40BinarySensorEntityDescription(
            key="fallback_operation_status",
            resource_id="/heatSources/fallbackOperation/status",
            name="Notbetrieb",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.PROBLEM,
            icon="mdi:alert-octagon",
        ),
        # System constraints & powers
        BoschK40BinarySensorEntityDescription(
            key="power_guard_active",
            resource_id="/system/powerGuard/active",
            name="Power Guard aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:shield-flash",
        ),
        BoschK40BinarySensorEntityDescription(
            key="power_limitation_active",
            resource_id="/system/powerLimitation/active",
            name="Leistungsbegrenzung aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:speedometer-slow",
        ),
        BoschK40BinarySensorEntityDescription(
            key="silent_mode_status",
            resource_id="/system/powerConstraints/silentMode/status",
            name="Flüsterbetrieb aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:volume-mute",
        ),
        BoschK40BinarySensorEntityDescription(
            key="maintenance_mode_status",
            resource_id="/system/powerConstraints/maintenanceMode/status",
            name="Wartungsmodus",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:wrench",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_heating_block",
            resource_id="/system/powerConstraints/externalInputs/heatingBlock/status",
            name="Heizsperre aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:radiator-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_cooling_block",
            resource_id="/system/powerConstraints/externalInputs/coolingBlock/status",
            name="Kühlsperre aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:snowflake-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_dhw_block",
            resource_id="/system/powerConstraints/externalInputs/dhwBlock/status",
            name="Warmwassersperre aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:water-boiler-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_pv_status",
            resource_id="/system/powerConstraints/externalInputs/pv/status",
            name="PV-Überschuss aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:solar-power",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_additional_heater_block",
            resource_id="/system/powerConstraints/externalInputs/additionalHeaterBlock/status",
            name="Zuheizersperre aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:heating-coil-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_appliance_power_block",
            resource_id="/system/powerConstraints/externalInputs/appliancePowerBlock/status",
            name="Geräteleistungssperre aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:power-plug-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_high_source_temp_stop_cooling",
            resource_id="/system/powerConstraints/highSourceTempStopCooling/status",
            name="Kühlsperre Hochtemperaturschutz aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.COLD,
            icon="mdi:snowflake-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_high_source_temp_stop_heating",
            resource_id="/system/powerConstraints/highSourceTempStopHeating/status",
            name="Heizsperre Hochtemperaturschutz aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.HEAT,
            icon="mdi:fire-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_low_source_temp_stop_cooling",
            resource_id="/system/powerConstraints/lowSourceTempStopCooling/status",
            name="Kühlsperre Tieftemperaturschutz aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.COLD,
            icon="mdi:snowflake-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_low_source_temp_stop_heating",
            resource_id="/system/powerConstraints/lowSourceTempStopHeating/status",
            name="Heizsperre Tieftemperaturschutz aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.HEAT,
            icon="mdi:fire-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_power_elec_desired",
            resource_id="/system/powerConstraints/powerElecDesired/status",
            name="Elektrische Leistungsvorgabe aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.POWER,
            icon="mdi:flash-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="pc_user_additional_heater_block",
            resource_id="/system/powerConstraints/userAdditionalHeaterBlock/status",
            name="Benutzer Zuheizersperre aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:heating-coil-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="vt_dhw_high_price_enable",
            resource_id="/system/variableTariff/dhw/highPriceEnable",
            name="Variabler Tarif Warmwasser Hochpreis aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:cash-fast",
        ),
        BoschK40BinarySensorEntityDescription(
            key="vt_dhw_low_price_enable",
            resource_id="/system/variableTariff/dhw/lowPriceEnable",
            name="Variabler Tarif Warmwasser Niedrigpreis aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:cash-100",
        ),
        BoschK40BinarySensorEntityDescription(
            key="additional_heater_primary_status",
            resource_id="/heatSources/additionalHeater/primary/status",
            name="Zuheizer Primärstatus",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.RUNNING,
            icon="mdi:heating-coil",
        ),
        BoschK40BinarySensorEntityDescription(
            key="eheater_status",
            resource_id="/heatSources/Source/eHeater/status",
            name="Elektroheizer Status",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.RUNNING,
            icon="mdi:heating-coil",
        ),
        BoschK40BinarySensorEntityDescription(
            key="external_input_1_state",
            resource_id="/heatSources/externalInputs/input1/state",
            name="Externer Eingang 1",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:electric-switch",
        ),
        BoschK40BinarySensorEntityDescription(
            key="external_input_2_state",
            resource_id="/heatSources/externalInputs/input2/state",
            name="Externer Eingang 2",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:electric-switch",
        ),
        BoschK40BinarySensorEntityDescription(
            key="external_input_3_state",
            resource_id="/heatSources/externalInputs/input3/state",
            name="Externer Eingang 3",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:electric-switch",
        ),
        BoschK40BinarySensorEntityDescription(
            key="external_input_4_state",
            resource_id="/heatSources/externalInputs/input4/state",
            name="Externer Eingang 4",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:electric-switch",
        ),
        BoschK40BinarySensorEntityDescription(
            key="external_inputs_cooling_block",
            resource_id="/heatSources/externalInputs/status/coolingBlock",
            name="Kühlsperre Extern aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.COLD,
            icon="mdi:snowflake-off",
        ),
        BoschK40BinarySensorEntityDescription(
            key="power_constraints_power_guard_status",
            resource_id="/system/powerConstraints/powerGuard/status",
            name="PowerGuard Status",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:shield-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="power_constraints_power_elec_limitation_status",
            resource_id="/system/powerConstraints/powerElecLimitation/status",
            name="Elektrische Leistungsbegrenzung aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:speedometer-slow",
        ),
        BoschK40BinarySensorEntityDescription(
            key="power_constraints_dhw_reduce_alarm",
            resource_id="/system/powerConstraints/dhwReduceTempOnAlarm/status",
            name="Warmwasser Reduzierung bei Alarm aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            device_class=BinarySensorDeviceClass.PROBLEM,
            icon="mdi:water-boiler-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="power_constraints_appliance_power_limit",
            resource_id="/system/powerConstraints/externalInputs/appliancePowerLimit/status",
            name="Geräteleistungsgrenze aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:flash-alert",
        ),
        BoschK40BinarySensorEntityDescription(
            key="variable_tariff_ch_optimization",
            resource_id="/system/variableTariff/ch/optimization",
            name="Variabler Tarif Heizung Optimierung aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:tune",
        ),
        BoschK40BinarySensorEntityDescription(
            key="variable_tariff_dhw_optimization",
            resource_id="/system/variableTariff/dhw/optimization",
            name="Variabler Tarif Warmwasser Optimierung aktiv",
            target_device_type=DEV_TYPE_HEAT_SOURCE,
            icon="mdi:tune",
        ),
    ]

    # DHW circuit binary sensors
    for dhw in CANDIDATE_DHW_CIRCUITS:
        num = dhw.replace("dhw", "")
        dev_name = f"Warmwasser {num}"
        descriptions.append(
            BoschK40BinarySensorEntityDescription(
                key=f"{dhw}_td_running_status",
                resource_id=f"/dhwCircuits/{dhw}/tdrunningStatus",
                name=f"Thermische Desinfektion {dev_name}",
                target_device_type=DEV_TYPE_DHW_CIRCUIT,
                device_sub_id=dhw,
                device_name=dev_name,
                device_class=BinarySensorDeviceClass.RUNNING,
                icon="mdi:shield-bug-outline",
            )
        )

    # Heating circuit binary sensors
    for hc in CANDIDATE_HEATING_CIRCUITS:
        num = hc.replace("hc", "")
        dev_name = f"Heizkreis {num}"
        descriptions.extend([
            BoschK40BinarySensorEntityDescription(
                key=f"{hc}_pump_status",
                resource_id=f"/heatingCircuits/{hc}/pumpStatus",
                name=f"Heizkreispumpe {dev_name}",
                target_device_type=DEV_TYPE_HEATING_CIRCUIT,
                device_sub_id=hc,
                device_name=dev_name,
                device_class=BinarySensorDeviceClass.RUNNING,
                icon="mdi:pump",
            ),
            BoschK40BinarySensorEntityDescription(
                key=f"{hc}_open_window_status",
                resource_id=f"/heatingCircuits/{hc}/openWindowDetection/status",
                name=f"Fenster-Offen-Erkennung {dev_name}",
                target_device_type=DEV_TYPE_HEATING_CIRCUIT,
                device_sub_id=hc,
                device_name=dev_name,
                device_class=BinarySensorDeviceClass.WINDOW,
                icon="mdi:window-open-variant",
            ),
        ])

    # Zone child lock
    for zone in CANDIDATE_ZONES:
        num = zone.replace("zone", "")
        dev_name = f"Zone {num}"
        descriptions.append(
            BoschK40BinarySensorEntityDescription(
                key=f"{zone}_child_lock",
                resource_id=f"/zones/{zone}/childLock",
                name=f"Kindersicherung {dev_name}",
                target_device_type=DEV_TYPE_ZONE,
                device_sub_id=zone,
                device_name=dev_name,
                device_class=BinarySensorDeviceClass.LOCK,
                icon="mdi:lock-outline",
            )
        )

    # RF device connectivity
    for dev in CANDIDATE_DEVICES:
        num = dev.replace("device", "")
        dev_name = f"Gerät {num}"
        descriptions.extend([
            BoschK40BinarySensorEntityDescription(
                key=f"{dev}_rf_connection_status",
                resource_id=f"/devices/{dev}/rfConnectionStatus",
                name=f"Verbindung {dev_name}",
                target_device_type=DEV_TYPE_DEVICE,
                device_sub_id=dev,
                device_name=dev_name,
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
                icon="mdi:signal",
            ),
            BoschK40BinarySensorEntityDescription(
                key=f"{dev}_rf_paired_status",
                resource_id=f"/devices/{dev}/rfPairedStatus",
                name=f"Pairing {dev_name}",
                target_device_type=DEV_TYPE_DEVICE,
                device_sub_id=dev,
                device_name=dev_name,
                icon="mdi:link-variant",
            ),
        ])

    return descriptions


def get_all_candidate_sensor_descriptions() -> list[BoschK40SensorEntityDescription]:
    """Return all known sensor descriptions across all candidates."""
    descriptions: list[BoschK40SensorEntityDescription] = []
    descriptions.extend(build_gateway_sensors())
    descriptions.extend(build_heat_source_global_sensors())

    for hs in CANDIDATE_HEAT_SOURCES:
        descriptions.extend(build_heat_source_unit_sensors(hs))

    for hc in CANDIDATE_HEATING_CIRCUITS:
        descriptions.extend(build_heating_circuit_sensors(hc))

    for dhw in CANDIDATE_DHW_CIRCUITS:
        descriptions.extend(build_dhw_circuit_sensors(dhw))

    for sc in CANDIDATE_SOLAR_CIRCUITS:
        descriptions.extend(build_solar_circuit_sensors(sc))

    for vz in CANDIDATE_VENTILATION_ZONES:
        descriptions.extend(build_ventilation_sensors(vz))

    descriptions.append(build_pool_sensor())

    for zone in CANDIDATE_ZONES:
        descriptions.extend(build_zone_sensors(zone))

    for dev in CANDIDATE_DEVICES:
        descriptions.extend(build_rf_device_sensors(dev))

    return descriptions


# ---------------------------------------------------------------------------
# DYNAMIC DESCRIPTION GENERATOR (für neue oder künftige Geräte/Werte)
# ---------------------------------------------------------------------------

SIGNAL_NAME_MAP: dict[str, tuple[str, SensorDeviceClass | None, SensorStateClass | None, Any]] = {
    "HYBMAN.ODUMONITOR.TC3Temp": ("Außeneinheit TC3 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TL2Temp": ("Außeneinheit TL2 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TR6Temp": ("Außeneinheit TR6 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TC0Temp": ("Außeneinheit TC0 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TA4Temp": ("Außeneinheit TA4 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TR1Temp": ("Außeneinheit TR1 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TR3Temp": ("Außeneinheit TR3 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.JR1Temp": ("Außeneinheit JR1 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TR4Temp": ("Außeneinheit TR4 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.JR0Temp": ("Außeneinheit JR0 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.ODUMONITOR.TR5Temp": ("Außeneinheit TR5 Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.TempFlowHeatPump": ("Wärmepumpe Vorlauftemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.TempReturnHeatPump": ("Wärmepumpe Rücklauftemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.TempSysReturn": ("System Rücklauftemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.TempMaxHp": ("Wärmepumpe Max. Vorlauftemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.HighestPermittedTemp": ("Höchste zulässige Temperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.LowOutdoorTempStopHeating": ("Min. Außentemperatur Heizgrenze", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.HighOutdoorTempStopHeating": ("Max. Außentemperatur Sommerabschaltung", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "HYBMAN.PumpSpeedSetp": ("Pumpendrehzahl Sollwert", None, SensorStateClass.MEASUREMENT, PERCENTAGE),
    "HYBMAN.ODUMONITOR.CompressorSpeedCurr": ("Verdichterdrehzahl ER1 Ist", None, SensorStateClass.MEASUREMENT, PERCENTAGE),
    "HYBMAN.CAN.CompressorSetp": ("Verdichterdrehzahl ER1 Sollwert", None, SensorStateClass.MEASUREMENT, PERCENTAGE),
    "HYBMAN.CAN.PositionVR1": ("Mischer Position VR1", None, SensorStateClass.MEASUREMENT, "%"),
    "HYBMAN.TimeTillNextCompressorStart": ("Restzeit bis Verdichterstart", SensorDeviceClass.DURATION, None, UnitOfTime.MINUTES),
    "HYBMAN.TimeTillNextCompressorStop": ("Restzeit bis Verdichterstopp", SensorDeviceClass.DURATION, None, UnitOfTime.MINUTES),
    "HYBMAN.OpTimeCompressorHeating": ("Verdichterlaufzeit Heizen", SensorDeviceClass.DURATION, SensorStateClass.TOTAL_INCREASING, UnitOfTime.HOURS),
    "HYBMAN.OpTimeCompressorDHW": ("Verdichterlaufzeit Warmwasser", SensorDeviceClass.DURATION, SensorStateClass.TOTAL_INCREASING, UnitOfTime.HOURS),
    "HYBMAN.SmartGridMode": ("Smart Grid Modus", None, None, None),
    "HYBMAN.EmergencyModeStatus": ("Notbetrieb Status", None, None, None),
    "SRC.OutdoorTemp": ("Außentemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SRC.IntFlowTemp": ("Vorlauftemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SRC.IntDHW.CylTemp": ("Warmwassertemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SRC.Fan.ActualSpeed": ("Gebläsedrehzahl", None, SensorStateClass.MEASUREMENT, "rpm"),
    "SRC.FlameCurrent": ("Flammenstrom", None, SensorStateClass.MEASUREMENT, "µA"),
    "SRC.DisplayCode": ("Display-Code", None, None, None),
    "HC1MOD.FlowTemp": ("Vorlauftemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SC.HC1.FlowTempSetp": ("Vorlauf Sollwert", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SC.HC1.MaxFlowTempSetp": ("Max. Vorlauf Sollwert", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SC.IntRoomTemp": ("Raumtemperatur Intern", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SC.DampOutdTemp": ("Gedämpfte Außentemperatur", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS),
    "SOLAR.HeatCount.Minus1DailySolarGain": ("Solarertrag Vortag", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
    "SOLAR.HeatCount.Minus1MonthlySolarGain": ("Solarertrag Vormonat", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
    "SOLAR.HeatCount.Minus1YearlySolarGain": ("Solarertrag Vorjahr", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR),
    "SOLAR.HeatCount.TotalLastMinus1HourGain": ("Solarertrag Letzte Stunde", SensorDeviceClass.ENERGY, None, UnitOfEnergy.KILO_WATT_HOUR),
    # EEBus (Gateway)
    "GWEEBUS.CEM.ID": ("EEBus CEM ID", None, None, None),
    "GWEEBUS.Status": ("EEBus Status", None, None, None),
    "GWEEBUS.CommissioningStatus": ("EEBus Inbetriebnahme Status", None, None, None),
}

SIGNAL_BINARY_MAP: dict[str, tuple[str, BinarySensorDeviceClass | None, str | None]] = {
    # HybridManager (HM200)
    "HYBMAN.PumpOn": ("Pumpe aktiv", BinarySensorDeviceClass.RUNNING, "mdi:water-pump"),
    "HYBMAN.CAN.DefrostActive": ("Abtauung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:snowflake-melt"),
    "HYBMAN.CAN.FourWayValveActive": ("4-Wege-Ventil aktiv", BinarySensorDeviceClass.OPENING, "mdi:valve"),
    "HYBMAN.CAN.DripPanHeaterActive": ("Kondensatwannenheizung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:heating-coil"),
    "HYBMAN.LowNoiseModeActive": ("Flüsterbetrieb aktiv", None, "mdi:volume-mute"),
    "HYBMAN.HeatUpSequence": ("Aufheizsequenz aktiv", BinarySensorDeviceClass.RUNNING, "mdi:fire"),
    "HYBMAN.CompSpeedLimitedDueToSilentMode": ("Verdichter im Flüsterbetrieb begrenzt", None, "mdi:speedometer-slow"),

    # Kessel (MC110 / Brenner)
    "SRC.RelayStatus.3WayValve": ("3-Wege-Ventil Kessel", BinarySensorDeviceClass.OPENING, "mdi:valve"),
    "SRC.DigInput.AirPressureSwitch": ("Differenzdruckwächter Kessel", BinarySensorDeviceClass.PROBLEM, "mdi:air-filter"),
    "SRC.AutoFillingActive": ("Automatische Befüllung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:water-pump"),
    "SRC.RelayStatus.CHPump": ("Heizkreispumpe Kessel", BinarySensorDeviceClass.RUNNING, "mdi:pump"),
    "SRC.OpStatus.ChimneySweeper": ("Schornsteinfegerbetrieb", None, "mdi:radiator"),
    "SRC.IntDHW.CircPumpStatus": ("Zirkulationspumpe Warmwasser", BinarySensorDeviceClass.RUNNING, "mdi:pump"),
    "SRC.IntDHW.DHURunning": ("Warmwasserbereitung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:water-boiler"),
    "SRC.DigInput.ExtCutOff": ("Externe Abschaltung Kessel", BinarySensorDeviceClass.POWER, "mdi:power-off"),
    "SRC.IntDHW.ExtraActive": ("Warmwasser Extra-Ladung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:water-plus"),
    "SRC.RelayStatus.Fan": ("Gebläse Kessel", BinarySensorDeviceClass.RUNNING, "mdi:fan"),
    "SRC.RelayStatus.GasValve1": ("Gasventil 1 Kessel", BinarySensorDeviceClass.OPENING, "mdi:valve-closed"),
    "SRC.RelayStatus.GasValve2": ("Gasventil 2 Kessel", BinarySensorDeviceClass.OPENING, "mdi:valve-closed"),
    "SRC.DigInput.OilTemperatureHigh": ("Öltemperatur zu hoch", BinarySensorDeviceClass.PROBLEM, "mdi:alert-circle"),
    "SRC.IntDHW.HeatUpActive": ("Warmwasser Aufheizung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:water-boiler-alert"),

    # Heating Circuit & System Controller
    "SC.HC1.RTSD.PreventionEcoModeActive": ("Frostschutz Eco-Modus aktiv", None, "mdi:snowflake-check"),
    "SC.HC1.FPD.Active": ("Frostschutz aktiv", None, "mdi:snowflake-alert"),
    "SC.DHW1.SD.ExtraActive": ("Warmwasser Extra-Ladung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:water-boiler"),
    "SC.HC1.RoTempSetpOpt.HeatUpStatus": ("Schnellaufheizung aktiv", BinarySensorDeviceClass.RUNNING, "mdi:fire"),
    "HC1MOD.FlowCtrl.PumpRequest": ("Pumpenanforderung Heizkreis 1", BinarySensorDeviceClass.RUNNING, "mdi:pump"),
}


def _determine_target_device(resource_id: str) -> tuple[str, str | None, str | None]:
    """Determine (target_device_type, device_sub_id, device_name) from resource path."""
    cleaned_path = resource_id.strip("/")
    parts = cleaned_path.split("/")

    dev_type = DEV_TYPE_HEAT_SOURCE
    sub_id = None
    dev_name = None

    if parts[0] == "gateway":
        dev_type = DEV_TYPE_GATEWAY
    elif parts[0] == "heatingCircuits" and len(parts) >= 2:
        dev_type = DEV_TYPE_HEATING_CIRCUIT
        sub_id = parts[1]
        dev_name = f"Heizkreis {sub_id.replace('hc', '')}"
    elif parts[0] == "dhwCircuits" and len(parts) >= 2:
        dev_type = DEV_TYPE_DHW_CIRCUIT
        sub_id = parts[1]
        dev_name = f"Warmwasser {sub_id.replace('dhw', '')}"
    elif parts[0] == "solarCircuits" and len(parts) >= 2:
        dev_type = DEV_TYPE_SOLAR_CIRCUIT
        sub_id = parts[1]
        dev_name = f"Solarkreis {sub_id.replace('sc', '')}"
    elif parts[0] == "ventilation" and len(parts) >= 2:
        dev_type = DEV_TYPE_VENTILATION
        sub_id = parts[1]
        dev_name = f"Lüftung {sub_id}"
    elif parts[0] == "zones" and len(parts) >= 2:
        dev_type = DEV_TYPE_ZONE
        sub_id = parts[1]
        dev_name = f"Zone {sub_id.replace('zone', '')}"
    elif parts[0] == "devices" and len(parts) >= 2:
        dev_type = DEV_TYPE_DEVICE
        sub_id = parts[1]
        dev_name = f"Gerät {sub_id.replace('device', '')}"
    elif parts[0] == "heatSources" and len(parts) >= 2 and parts[1].startswith("hs"):
        dev_type = DEV_TYPE_HEAT_SOURCE
        sub_id = parts[1]
        dev_name = f"Wärmeerzeuger {sub_id.upper()}"
    elif parts[0] == "signals" and len(parts) >= 2:
        sig_id = parts[1]
        if sig_id.startswith("HYBMAN"):
            dev_type = DEV_TYPE_HEAT_SOURCE
            sub_id = "hybman"
            dev_name = "HybridManager"
        elif sig_id.startswith("SRC"):
            dev_type = DEV_TYPE_HEAT_SOURCE
            sub_id = "kessel"
            dev_name = "Kessel"
        elif sig_id.startswith("SC.HC") or sig_id.startswith("HC1MOD"):
            dev_type = DEV_TYPE_HEATING_CIRCUIT
            sub_id = "hc1"
            dev_name = "Heizkreis 1"
        elif sig_id.startswith("SC.DHW"):
            dev_type = DEV_TYPE_DHW_CIRCUIT
            sub_id = "dhw1"
            dev_name = "Warmwasser 1"
        elif sig_id.startswith("SOLAR"):
            dev_type = DEV_TYPE_SOLAR_CIRCUIT
            sub_id = "sc1"
            dev_name = "Solarkreis 1"
        elif sig_id.startswith("GWEEBUS"):
            dev_type = DEV_TYPE_GATEWAY
            sub_id = None
            dev_name = "Gateway"
        else:
            dev_type = DEV_TYPE_HEAT_SOURCE
            sub_id = "hybman"
            dev_name = "HybridManager"
    elif parts[0] == "pool":
        dev_type = DEV_TYPE_POOL

    return dev_type, sub_id, dev_name


def is_boolean_endpoint(
    resource_id: str,
    res_data: dict[str, Any],
) -> bool:
    """Determine whether an endpoint is a boolean entity."""
    # 1. Check known binary signals mapping first
    parts = resource_id.strip("/").split("/")
    if parts[0] == "signals" and len(parts) >= 2:
        sig_id = parts[1]
        if sig_id in SIGNAL_BINARY_MAP:
            return True

    # 2. Check Bosch type
    type_str = str(res_data.get("type", "")).lower()
    if type_str in ("booleanvalue", "boolvalue", "boolean", "bool"):
        return True

    # 3. Check Python bool
    val = res_data.get("value")
    if isinstance(val, bool):
        return True

    # 4. Check allowedValues
    allowed = res_data.get("allowedValues")
    if isinstance(allowed, list) and len(allowed) == 2:
        norm = {str(x).strip().lower() for x in allowed}
        if norm in (
            {"true", "false"},
            {"on", "off"},
            {"yes", "no"},
            {"active", "inactive"},
            {"enabled", "disabled"},
            {"1", "0"},
        ):
            return True

    # 5. Check string values if exactly true/false
    if isinstance(val, str):
        val_clean = val.strip().lower()
        if val_clean in ("true", "false"):
            return True
        # "on"/"off" is boolean if allowedValues is either absent or length 2
        if val_clean in ("on", "off"):
            if not allowed or (isinstance(allowed, list) and len(allowed) <= 2):
                return True

    # 6. Check signal naming conventions
    res_lower = resource_id.lower()
    if "/signals/" in res_lower:
        keywords = (
            "relaystatus.",
            "diginput.",
            ".active",
            "autofillingactive",
            "pumpon",
            "dhurunning",
            "circpumpstatus",
            "heatupsequence",
            "pumprequest",
            "chimneysweeper",
        )
        if any(k in res_lower for k in keywords):
            return True

    return False


def create_dynamic_binary_sensor_description(
    resource_id: str,
    res_data: dict[str, Any],
) -> BoschK40BinarySensorEntityDescription:
    """Generate a binary sensor description dynamically from raw endpoint data."""
    cleaned_path = resource_id.strip("/")
    parts = cleaned_path.split("/")

    dev_type, sub_id, dev_name = _determine_target_device(resource_id)

    device_class: BinarySensorDeviceClass | None = None
    icon: str | None = None
    full_name: str | None = None

    if parts[0] == "signals" and len(parts) >= 2:
        sig_id = parts[1]
        if sig_id in SIGNAL_BINARY_MAP:
            full_name, device_class, icon = SIGNAL_BINARY_MAP[sig_id]
        else:
            clean_leaf = sig_id.split(".")[-1]
            readable_leaf = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", clean_leaf)
            readable_leaf = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", readable_leaf).strip().title()
            full_name = readable_leaf
    else:
        leaf_name = parts[-1]
        readable_leaf = re.sub(r"([A-Z])", r" \1", leaf_name).strip().title()
        full_name = f"{readable_leaf} {dev_name}" if dev_name else readable_leaf

    res_lower = resource_id.lower()
    name_lower = full_name.lower() if full_name else ""

    if device_class is None:
        if (
            "pump" in res_lower
            or "pumpe" in name_lower
            or "running" in res_lower
            or "aktiv" in name_lower
            or "active" in res_lower
            or "heatup" in res_lower
            or "defrost" in res_lower
            or "fan" in res_lower
            or "gebläse" in name_lower
        ):
            device_class = BinarySensorDeviceClass.RUNNING
        elif (
            "problem" in res_lower
            or "alarm" in res_lower
            or "error" in res_lower
            or "fault" in res_lower
            or "switch" in res_lower
        ):
            device_class = BinarySensorDeviceClass.PROBLEM
        elif "valve" in res_lower or "ventil" in name_lower:
            device_class = BinarySensorDeviceClass.OPENING
        elif "cooling" in res_lower:
            device_class = BinarySensorDeviceClass.COLD
        elif "heating" in res_lower:
            device_class = BinarySensorDeviceClass.HEAT
        elif "power" in res_lower or "cutoff" in res_lower or "cut_off" in res_lower:
            device_class = BinarySensorDeviceClass.POWER
        elif "connect" in res_lower or "verbindung" in name_lower:
            device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif "lock" in res_lower or "sperre" in name_lower:
            device_class = BinarySensorDeviceClass.LOCK

    if icon is None:
        if "pump" in res_lower or "pumpe" in name_lower:
            icon = "mdi:water-pump"
        elif "fan" in res_lower or "gebläse" in name_lower:
            icon = "mdi:fan"
        elif "valve" in res_lower or "ventil" in name_lower:
            icon = "mdi:valve"
        elif "defrost" in res_lower or "abtauung" in name_lower:
            icon = "mdi:snowflake-melt"
        elif "heat" in res_lower or "feuer" in name_lower:
            icon = "mdi:fire"
        elif "switch" in res_lower or "schalter" in name_lower:
            icon = "mdi:toggle-switch"
        elif "power" in res_lower:
            icon = "mdi:flash"

    return BoschK40BinarySensorEntityDescription(
        key=f"dyn_{cleaned_path.replace('/', '_').replace('.', '_')}",
        resource_id=resource_id,
        name=full_name,
        target_device_type=dev_type,
        device_sub_id=sub_id,
        device_name=dev_name,
        device_class=device_class,
        icon=icon,
    )


def create_dynamic_sensor_description(
    resource_id: str,
    res_data: dict[str, Any],
) -> BoschK40SensorEntityDescription:
    """Generate a sensor description dynamically from raw endpoint data.

    Allows any new device or future endpoint to be added automatically without code changes.
    """
    cleaned_path = resource_id.strip("/")
    parts = cleaned_path.split("/")

    dev_type, sub_id, dev_name = _determine_target_device(resource_id)

    # 2. Determine Unit, DeviceClass & StateClass
    unit = res_data.get("unitOfMeasure") or res_data.get("unit")
    device_class = None
    state_class = None

    if unit in ("C", "°C"):
        device_class = SensorDeviceClass.TEMPERATURE
        state_class = SensorStateClass.MEASUREMENT
        unit = UnitOfTemperature.CELSIUS
    elif unit == "%":
        state_class = SensorStateClass.MEASUREMENT
        unit = PERCENTAGE
        if "humidity" in resource_id.lower():
            device_class = SensorDeviceClass.HUMIDITY
    elif unit in ("bar", "mbar"):
        device_class = SensorDeviceClass.PRESSURE
        state_class = SensorStateClass.MEASUREMENT
        unit = UnitOfPressure.BAR
    elif unit in ("W", "kW"):
        device_class = SensorDeviceClass.POWER
        state_class = SensorStateClass.MEASUREMENT
        unit = UnitOfPower.WATT if unit == "W" else UnitOfPower.KILO_WATT
    elif unit in ("Wh", "wh", "kWh"):
        device_class = SensorDeviceClass.ENERGY
        state_class = SensorStateClass.TOTAL_INCREASING
        unit = UnitOfEnergy.WATT_HOUR if unit.lower() == "wh" else UnitOfEnergy.KILO_WATT_HOUR
    elif unit in ("s", "mins", "hours"):
        device_class = SensorDeviceClass.DURATION
        unit = (
            UnitOfTime.SECONDS if unit == "s"
            else UnitOfTime.MINUTES if unit == "mins"
            else UnitOfTime.HOURS
        )
    elif unit in ("ppm",):
        device_class = SensorDeviceClass.AQI
        state_class = SensorStateClass.MEASUREMENT
        unit = "ppm"
    elif unit in ("db", "dBm"):
        device_class = SensorDeviceClass.SIGNAL_STRENGTH
        state_class = SensorStateClass.MEASUREMENT
        unit = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    # 3. Create readable name
    if parts[0] == "signals" and len(parts) >= 2:
        sig_id = parts[1]
        if sig_id in SIGNAL_NAME_MAP:
            friendly_name, mapped_class, mapped_state, mapped_unit = SIGNAL_NAME_MAP[sig_id]
            if mapped_class:
                device_class = mapped_class
            if mapped_state:
                state_class = mapped_state
            if mapped_unit:
                unit = mapped_unit
            full_name = friendly_name
        else:
            clean_leaf = sig_id.split(".")[-1]
            readable_leaf = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", clean_leaf)
            readable_leaf = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", readable_leaf).strip().title()
            if readable_leaf.lower().endswith("temp") or "temperature" in readable_leaf.lower():
                if not device_class:
                    device_class = SensorDeviceClass.TEMPERATURE
                    state_class = SensorStateClass.MEASUREMENT
                    unit = UnitOfTemperature.CELSIUS
            full_name = readable_leaf
    else:
        leaf_name = parts[-1]
        readable_leaf = re.sub(r"([A-Z])", r" \1", leaf_name).strip().title()
        full_name = f"{readable_leaf} {dev_name}" if dev_name else readable_leaf

    value_fn = None
    icon = None
    res_lower = resource_id.lower()
    name_lower = full_name.lower()
    if "smartgridmode" in res_lower:
        value_fn = parse_smart_grid_mode
        icon = "mdi:transmission-tower"
    elif "compressorspeed" in res_lower or "verdichterdrehzahl" in name_lower:
        icon = "mdi:speedometer"
    elif "compressor" in res_lower or "verdichter" in name_lower:
        icon = "mdi:heat-pump"
    elif "pumpspeed" in res_lower or "pumpendrehzahl" in name_lower:
        icon = "mdi:speedometer"
    elif "pump" in res_lower or "pumpe" in name_lower:
        icon = "mdi:water-pump"
    elif "fan" in res_lower or "gebläse" in name_lower:
        icon = "mdi:fan"
    elif device_class == SensorDeviceClass.TEMPERATURE:
        icon = "mdi:thermometer"
    elif device_class == SensorDeviceClass.ENERGY:
        icon = "mdi:lightning-bolt"

    return BoschK40SensorEntityDescription(
        key=f"dyn_{cleaned_path.replace('/', '_').replace('.', '_')}",
        resource_id=resource_id,
        name=full_name,
        target_device_type=dev_type,
        device_sub_id=sub_id,
        device_name=dev_name,
        device_class=device_class,
        state_class=state_class,
        native_unit_of_measurement=unit,
        icon=icon,
        value_fn=value_fn,
    )
