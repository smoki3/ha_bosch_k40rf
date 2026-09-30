"""Sensor platform for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_GATEWAY_BRAND,
    CONF_GATEWAY_MAC,
    CONF_GATEWAY_MODEL,
    DEV_TYPE_DEVICE,
    DEV_TYPE_DHW_CIRCUIT,
    DEV_TYPE_GATEWAY,
    DEV_TYPE_HEAT_SOURCE,
    DEV_TYPE_HEATING_CIRCUIT,
    DEV_TYPE_POOL,
    DEV_TYPE_SOLAR_CIRCUIT,
    DEV_TYPE_VENTILATION,
    DEV_TYPE_ZONE,
    DOMAIN,
)
from .coordinator import BoschK40DataUpdateCoordinator
from .models import BoschK40SensorEntityDescription, sanitize_serial_number

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bosch K 40 RF sensor entities based on confirmed coordinator data."""
    coordinator: BoschK40DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    gateway_unique_id = (
        entry.unique_id
        or coordinator.gateway_info.get("unique_id")
        or coordinator.client.host
    )

    registered_unique_ids: set[str] = set()

    def _get_new_entities() -> list[BoschK40Sensor]:
        new_entities: list[BoschK40Sensor] = []
        for description in coordinator.active_sensor_descriptions:
            cleaned_path = description.resource_id.replace("/", "_").strip("_")
            val_key_suffix = f"_{description.value_key}" if description.value_key else ""
            unique_id = f"{gateway_unique_id}_{cleaned_path}{val_key_suffix}"

            if unique_id in registered_unique_ids:
                continue

            sensor = BoschK40Sensor(
                coordinator=coordinator,
                entry=entry,
                description=description,
                gateway_unique_id=gateway_unique_id,
            )

            # Strictly verify that this entity currently delivers valid data.
            # Do NOT create entities that have no data or return invalid sentinels.
            val = sensor.native_value
            if val is None or val in ("", "unknown", "unavailable"):
                continue

            registered_unique_ids.add(unique_id)
            new_entities.append(sensor)
        return new_entities

    # Initial registration: only entities with verified valid data
    initial_entities = _get_new_entities()
    _LOGGER.info("Registered %s Bosch K 40 RF sensor entities with valid data", len(initial_entities))
    async_add_entities(initial_entities)

    # Dynamic registration: listen for newly discovered devices/endpoints or data in the background
    @callback
    def _async_check_for_new_sensors() -> None:
        new_sensors = _get_new_entities()
        if new_sensors:
            _LOGGER.info("Dynamically registered %s new Bosch K 40 RF sensor(s)", len(new_sensors))
            async_add_entities(new_sensors)

    entry.async_on_unload(coordinator.async_add_listener(_async_check_for_new_sensors))


class BoschK40Sensor(CoordinatorEntity[BoschK40DataUpdateCoordinator], SensorEntity):
    """Representation of a Bosch K 40 RF sensor entity."""

    _attr_has_entity_name = True
    entity_description: BoschK40SensorEntityDescription

    def __init__(
        self,
        coordinator: BoschK40DataUpdateCoordinator,
        entry: ConfigEntry,
        description: BoschK40SensorEntityDescription,
        gateway_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.entry = entry
        self._gateway_unique_id = gateway_unique_id

        cleaned_path = description.resource_id.replace("/", "_").strip("_")
        val_key_suffix = f"_{description.value_key}" if description.value_key else ""
        self._attr_unique_id = f"{gateway_unique_id}_{cleaned_path}{val_key_suffix}"

    @property
    def name(self) -> str | None:
        """Return friendly name with smart hybrid naming."""
        if self.entity_description.translation_key:
            return None
        base_name = self.entity_description.name
        if not base_name:
            return None
        if base_name.startswith("HybridManager "):
            base_name = base_name.replace("HybridManager ", "", 1)
        if self.coordinator.is_hybrid_system:
            if self.entity_description.resource_id == "/heatSources/numberOfStarts":
                return "Brennerstarts Gesamt"
            if self.entity_description.resource_id == "/heatSources/workingTime/totalSystem":
                return "Betriebszeit Kessel Gesamt"
            if self.entity_description.resource_id == "/heatSources/actualModulation":
                return "Modulation Kessel"
            if self.entity_description.resource_id == "/heatSources/actualHeatDemand":
                return "Wärmebedarf Kessel"
            if (
                self.entity_description.resource_id == "/heatSources/emon/totalConsumption"
                and self.entity_description.value_key == "outputProduced"
            ):
                return "Erzeugte Wärmeenergie Kessel Gesamt"
            if (
                self.entity_description.resource_id == "/heatSources/emon/chConsumption"
                and self.entity_description.value_key == "outputProduced"
            ):
                return "Erzeugte Wärmeenergie Kessel Heizung"
            if (
                self.entity_description.resource_id == "/heatSources/emon/dhwConsumption"
                and self.entity_description.value_key == "outputProduced"
            ):
                return "Erzeugte Wärmeenergie Kessel Warmwasser"

            if self.entity_description.device_sub_id == "hs1":
                return base_name.replace(" HS1", " Kessel").replace(" hs1", " Kessel")
            if self.entity_description.device_sub_id == "hs2":
                return base_name.replace(" HS2", " Wärmepumpe").replace(" hs2", " Wärmepumpe")
        elif self.entity_description.device_sub_id == "hs1":
            return base_name.replace(" HS1", "").replace(" hs1", "")
        return base_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info with future-proof parent device link."""
        return self._build_device_info(self._gateway_unique_id)

    def _build_device_info(self, gateway_unique_id: str) -> DeviceInfo:
        """Build hierarchical DeviceInfo for Parent Gateway or Child Device."""
        brand = (
            self.coordinator.gateway_info.get("brand")
            or self.entry.data.get(CONF_GATEWAY_BRAND)
            or "Bosch"
        )
        model = (
            self.coordinator.gateway_info.get("model")
            or self.entry.data.get(CONF_GATEWAY_MODEL)
            or "Connect-Key K 40 RF"
        )
        firmware = (
            self.coordinator.gateway_info.get("firmware")
            or self.entry.data.get("firmware")
        )
        hardware = self.coordinator.gateway_info.get("hardware")
        mac = (
            self.coordinator.gateway_info.get("mac")
            or self.entry.data.get(CONF_GATEWAY_MAC)
        )

        dev_type = self.entity_description.target_device_type
        sub_id = self.entity_description.device_sub_id

        # 1. Parent Gateway Device
        if dev_type == DEV_TYPE_GATEWAY:
            gw_mod = (
                self.coordinator.get_basic_info_module(hw_ident="MX400")
                or self.coordinator.get_basic_info_module(hw_ident="K40RF")
            )
            gw_ver = (gw_mod.get("Ver") if gw_mod else None) or firmware
            gw_sn = sanitize_serial_number(
                (
                    gw_mod.get("ModuleSerialNumber")
                    if gw_mod and gw_mod.get("ModuleSerialNumber")
                    else None
                )
                or self.coordinator.gateway_info.get("serial_number")
            )
            connections = set()
            if mac:
                connections.add((CONNECTION_NETWORK_MAC, mac))
            return DeviceInfo(
                identifiers={(DOMAIN, gateway_unique_id)},
                name=f"{brand} Connect-Key K 40 RF Gateway",
                manufacturer=brand,
                model=model,
                sw_version=gw_ver,
                hw_version=hardware,
                serial_number=gw_sn,
                connections=connections,
            )

        # 2. Child Devices
        via_kwargs: dict[str, Any] = {"via_device": (DOMAIN, gateway_unique_id)}

        if dev_type == DEV_TYPE_HEAT_SOURCE:
            # In hybrid systems: cleanly route Kessel, Solar and HybridManager metrics
            if self.coordinator.is_hybrid_system:
                kessel_resource_exact = (
                    "/heatSources/flameStatus",
                    "/heatSources/actualModulation",
                    "/heatSources/actualHeatDemand",
                    "/heatSources/numberOfStarts",
                    "/heatSources/workingTime/totalSystem",
                )
                is_burner_emon = (
                    self.entity_description.resource_id.startswith("/heatSources/emon/")
                    and self.entity_description.value_key == "burner"
                )
                is_kessel_output_emon = (
                    self.entity_description.resource_id.startswith("/heatSources/emon/")
                    and self.entity_description.value_key == "outputProduced"
                    and sub_id != "hs2"
                )
                if (
                    sub_id == "kessel"
                    or sub_id == "hs1"
                    or self.entity_description.resource_id in kessel_resource_exact
                    or is_burner_emon
                    or is_kessel_output_emon
                ):
                    k_mod = (
                        self.coordinator.get_basic_info_module(hw_ident="MC")
                        or self.coordinator.get_basic_info_module(hw_ident="BC")
                    )
                    k_hw = (k_mod.get("ModuleHwIdentStr") if k_mod else None) or "MC110"
                    k_ver = k_mod.get("Ver") if k_mod else None
                    k_sn = sanitize_serial_number(k_mod.get("ModuleSerialNumber")) if k_mod else None
                    return DeviceInfo(
                        identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source_kessel")},
                        name=f"{brand} Kessel ({k_hw})" if k_hw != "Kessel" else f"{brand} Kessel",
                        manufacturer=brand,
                        model=f"Kessel / Brenner ({k_hw})",
                        sw_version=k_ver,
                        serial_number=k_sn,
                        **via_kwargs,
                    )

                # Route solar energy to Solarkreis
                if (
                    self.entity_description.resource_id.startswith("/heatSources/emon/")
                    and self.entity_description.value_key == "solar"
                ):
                    sm_mod = self.coordinator.get_basic_info_module(hw_ident="SM")
                    sm_hw = sm_mod.get("ModuleHwIdentStr") if sm_mod else None
                    sm_ver = sm_mod.get("Ver") if sm_mod else None
                    sm_sn = sanitize_serial_number(sm_mod.get("ModuleSerialNumber")) if sm_mod else None
                    model_name = f"Solarkreis ({sm_hw})" if sm_hw else "Solarkreis"
                    return DeviceInfo(
                        identifiers={(DOMAIN, f"{gateway_unique_id}_solar_sc1")},
                        name=f"{brand} Solarkreis 1",
                        manufacturer=brand,
                        model=model_name,
                        sw_version=sm_ver,
                        serial_number=sm_sn,
                        **via_kwargs,
                    )

                # Heat Pump (WLW MB-7 AR / hs2)
                # Keep strictly heat pump specific resources on the heat pump device:
                # - sub_id == "hs2"
                # - compressor power or sensors
                # - electrical consumption for heat pump
                is_hp_specific = (
                    sub_id == "hs2"
                    or self.entity_description.resource_id.startswith("/heatSources/hs2/")
                    or self.entity_description.resource_id.startswith("/heatSources/compressor/")
                    or self.entity_description.resource_id == "/heatSources/powerElecActual"
                    or (
                        self.entity_description.resource_id.startswith("/heatSources/emon/")
                        and self.entity_description.value_key in ("electricity", "compressor")
                    )
                    or self.entity_description.resource_id.startswith("/heatSources/sensors/")
                )
                if not is_hp_specific:
                    # All general heat source & system level resources route to HybridManager (HM200)
                    hm_mod = (
                        self.coordinator.get_basic_info_module(hw_ident="HM200")
                        or self.coordinator.get_basic_info_module(hw_ident="HM")
                    )
                    hm_hw = (hm_mod.get("ModuleHwIdentStr") if hm_mod else None) or "HM200.2"
                    hm_ver = hm_mod.get("Ver") if hm_mod else None
                    hm_sn = sanitize_serial_number(hm_mod.get("ModuleSerialNumber")) if hm_mod else None
                    return DeviceInfo(
                        identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source_hybman")},
                        name=f"{brand} HybridManager ({hm_hw})" if hm_hw else f"{brand} HybridManager",
                        manufacturer=brand,
                        model=f"HybridManager {hm_hw}" if hm_hw else "HybridManager",
                        sw_version=hm_ver,
                        serial_number=hm_sn,
                        **via_kwargs,
                    )

            # In non-hybrid systems or if sub_id is kessel
            if sub_id == "kessel":
                k_mod = (
                    self.coordinator.get_basic_info_module(hw_ident="MC")
                    or self.coordinator.get_basic_info_module(hw_ident="BC")
                )
                k_hw = (k_mod.get("ModuleHwIdentStr") if k_mod else None) or "MC110"
                k_ver = k_mod.get("Ver") if k_mod else None
                k_sn = sanitize_serial_number(k_mod.get("ModuleSerialNumber")) if k_mod else None
                return DeviceInfo(
                    identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source_kessel")},
                    name=f"{brand} Kessel ({k_hw})" if k_hw != "Kessel" else f"{brand} Kessel",
                    manufacturer=brand,
                    model=f"Kessel / Brenner ({k_hw})",
                    sw_version=k_ver,
                    serial_number=k_sn,
                    **via_kwargs,
                )

            # Primary Heat Pump / Wärmepumpe
            # In hybrid systems: hs2 or heat pump specific endpoints
            # In non-hybrid systems: hs1 (or None) is the heat pump
            if (
                sub_id is None
                or sub_id == "hs2"
                or (not self.coordinator.is_hybrid_system and sub_id == "hs1")
            ):
                appliance = self.coordinator.get_basic_info_module(is_appliance=True)
                prod_name = appliance.get("ProductName") if appliance else None
                app_ver = appliance.get("Ver") if appliance else None
                app_sn = sanitize_serial_number(appliance.get("ProductSerialNumber") or appliance.get("ModuleSerialNumber")) if appliance else None
                return DeviceInfo(
                    identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source")},
                    name=f"{brand} {prod_name}" if prod_name else f"{brand} Wärmeerzeuger",
                    manufacturer=brand,
                    model=prod_name or "Wärmeerzeuger / Wärmepumpe",
                    sw_version=app_ver,
                    serial_number=app_sn,
                    **via_kwargs,
                )

            # Any other heat source unit (e.g. hs3, hs4 in larger cascades)
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or f'Wärmeerzeuger {sub_id.upper()}'}",
                manufacturer=brand,
                model=f"Wärmeerzeuger {sub_id.upper()}",
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_HEATING_CIRCUIT:
            mm_mod = self.coordinator.get_basic_info_module(hw_ident="MM")
            mm_hw = mm_mod.get("ModuleHwIdentStr") if mm_mod else None
            mm_ver = mm_mod.get("Ver") if mm_mod else None
            mm_sn = sanitize_serial_number(mm_mod.get("ModuleSerialNumber")) if mm_mod else None
            model_name = f"Heizkreis ({mm_hw})" if mm_hw else "Heizkreis"
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_heating_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or 'Heizkreis'}",
                manufacturer=brand,
                model=model_name,
                sw_version=mm_ver,
                serial_number=mm_sn,
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_DHW_CIRCUIT:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_dhw_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or 'Warmwasser'}",
                manufacturer=brand,
                model="Warmwasserkreis",
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_SOLAR_CIRCUIT:
            sm_mod = self.coordinator.get_basic_info_module(hw_ident="SM")
            sm_hw = sm_mod.get("ModuleHwIdentStr") if sm_mod else None
            sm_ver = sm_mod.get("Ver") if sm_mod else None
            sm_sn = sanitize_serial_number(sm_mod.get("ModuleSerialNumber")) if sm_mod else None
            model_name = f"Solarkreis ({sm_hw})" if sm_hw else "Solarkreis"
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_solar_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or 'Solarkreis'}",
                manufacturer=brand,
                model=model_name,
                sw_version=sm_ver,
                serial_number=sm_sn,
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_VENTILATION:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_ventilation_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or 'Lüftung'}",
                manufacturer=brand,
                model="Lüftungseinheit",
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_ZONE:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_zone_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or 'Zone'}",
                manufacturer=brand,
                model="Heizzone",
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_DEVICE:
            rf_name = self.coordinator.get_value(f"/devices/{sub_id}/name")
            rf_type = self.coordinator.get_value(f"/devices/{sub_id}/type")
            rf_fw = self.coordinator.get_value(f"/devices/{sub_id}/versionFirmware")
            rf_sgtin = self.coordinator.get_value(f"/devices/{sub_id}/sgtin")
            dev_label = str(rf_name or rf_type or "Funk-Gerät")
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_{sub_id}")},
                name=f"{brand} {self.entity_description.device_name or 'Gerät'} ({dev_label})" if rf_name else f"{brand} {self.entity_description.device_name or 'Gerät'}",
                manufacturer=brand,
                model=dev_label,
                sw_version=str(rf_fw) if rf_fw else None,
                serial_number=sanitize_serial_number(rf_sgtin),
                **via_kwargs,
            )

        if dev_type == DEV_TYPE_POOL:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{gateway_unique_id}_pool")},
                name=f"{brand} Pool",
                manufacturer=brand,
                model="Pool",
                **via_kwargs,
            )

        return DeviceInfo(
            identifiers={(DOMAIN, gateway_unique_id)},
            name=f"{brand} Connect-Key K 40 RF",
            manufacturer=brand,
        )

    @property
    def native_value(self) -> Any:
        """Extract and safely convert the native value from coordinator data."""
        if self.entity_description.coordinator_fn:
            try:
                return self.entity_description.coordinator_fn(self.coordinator)
            except Exception as err:
                _LOGGER.debug("Error computing coordinator_fn for %s: %s", self.entity_id, err)
                return None

        res_data = self.coordinator.data.get(self.entity_description.resource_id)
        if not isinstance(res_data, dict):
            if self.entity_description.resource_id in (
                "/signals/HYBMAN.TimeTillNextCompressorStart",
                "/signals/HYBMAN.TimeTillNextCompressorStop",
            ):
                return 0
            if self.entity_description.resource_id == "/heatSources/hybrid/activeHeatSource":
                return "Keiner (Standby)"
            return None

        # Check for invalid states reported by gateway (e.g. state: [{"invalid": 255}])
        state_list = res_data.get("state")
        raw_val = res_data.get("value")

        # Handle subkeys (e.g. value_key="outputProduced", "burner", "solar", "total", "ch", "dhw", etc.)
        if self.entity_description.value_key:
            target_key = self.entity_description.value_key
            values_list = res_data.get("values")
            raw_val = None
            if isinstance(values_list, list):
                for item in values_list:
                    if isinstance(item, dict) and target_key in item:
                        raw_val = item[target_key]
                        break
        elif not self.entity_description.value_fn and (res_data.get("type") == "emonValue" or "values" in res_data):
            values_list = res_data.get("values")
            if isinstance(values_list, list) and values_list:
                first = values_list[0]
                if isinstance(first, dict):
                    raw_val = first.get("total", next(iter(first.values()), None))

        # Custom transformation function if provided (e.g. basicInfo, notifications, working_time)
        if self.entity_description.value_fn:
            try:
                # If value_key was used, pass the extracted subkey value;
                # otherwise pass values list (if present) or raw_val
                if self.entity_description.value_key:
                    arg = raw_val
                elif "values" in res_data:
                    arg = res_data.get("values")
                else:
                    arg = raw_val
                return self.entity_description.value_fn(arg)
            except Exception as err:
                _LOGGER.debug("Error transforming value for %s: %s", self.entity_id, err)

        if raw_val is None:
            if self.entity_description.resource_id in (
                "/signals/HYBMAN.TimeTillNextCompressorStart",
                "/signals/HYBMAN.TimeTillNextCompressorStop",
            ):
                return 0
            if self.entity_description.resource_id == "/heatSources/hybrid/activeHeatSource":
                return "Keiner (Standby)"
            return None

        # Check invalid sentinel values from device
        if isinstance(state_list, list):
            for s in state_list:
                if isinstance(s, dict) and "invalid" in s:
                    if raw_val == s["invalid"]:
                        return None

        # Check empty or sentinel strings
        if isinstance(raw_val, str):
            val_clean = raw_val.strip()
            if not val_clean or val_clean.lower() in ("unknown", "unavailable", "null"):
                return None

        # Check standard Bosch sensor fault sentinels (-32768, 65535)
        if isinstance(raw_val, (int, float)):
            if raw_val in (-32768, -3276.8, 65535, 255) and self.entity_description.device_class == SensorDeviceClass.TEMPERATURE:
                return None

        # Numeric conversions
        if self.entity_description.device_class in (
            SensorDeviceClass.TEMPERATURE,
            SensorDeviceClass.PRESSURE,
            SensorDeviceClass.POWER,
            SensorDeviceClass.ENERGY,
            SensorDeviceClass.HUMIDITY,
            SensorDeviceClass.AQI,
            SensorDeviceClass.SIGNAL_STRENGTH,
            SensorDeviceClass.DURATION,
        ):
            try:
                float_val = float(raw_val)
                if float_val.is_integer() and self.entity_description.device_class in (
                    SensorDeviceClass.DURATION,
                    SensorDeviceClass.AQI,
                ):
                    return int(float_val)
                return round(float_val, 2)
            except (ValueError, TypeError):
                return None

        if self.entity_description.state_class in ("total_increasing", SensorStateClass.TOTAL_INCREASING):
            try:
                float_val = float(raw_val)
                if float_val.is_integer():
                    return int(float_val)
                return round(float_val, 2)
            except (ValueError, TypeError):
                return raw_val

        return raw_val

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for diagnostic context."""
        attrs: dict[str, Any] = {}
        if self.entity_description.resource_id == "/signals/SC.InstallationDate":
            day = self.coordinator.get_value("/signals/SC.InstallationDate.Day")
            month = self.coordinator.get_value("/signals/SC.InstallationDate.Month")
            year = self.coordinator.get_value("/signals/SC.InstallationDate.Year")
            if day is not None:
                attrs["day"] = day
            if month is not None:
                attrs["month"] = month
            if year is not None:
                attrs["year"] = year
            return attrs

        res_data = self.coordinator.data.get(self.entity_description.resource_id)
        if isinstance(res_data, dict):
            if "type" in res_data:
                attrs["resource_type"] = res_data["type"]
            if "writeable" in res_data:
                attrs["writeable"] = bool(res_data["writeable"])
            if "allowedValues" in res_data:
                attrs["allowed_values"] = res_data["allowedValues"]
            if "unitOfMeasure" in res_data:
                attrs["gateway_unit"] = res_data["unitOfMeasure"]
            if "values" in res_data and isinstance(res_data["values"], list):
                attrs["raw_values"] = res_data["values"]
            if "smartgridmode" in self.entity_description.resource_id.lower():
                val = res_data.get("value")
                if val is not None:
                    try:
                        attrs["mode_code"] = int(val)
                    except (ValueError, TypeError):
                        attrs["mode_code"] = val
        return attrs
