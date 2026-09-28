"""Binary sensor platform for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)
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
from .models import BoschK40BinarySensorEntityDescription

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bosch K 40 RF binary sensor entities based on confirmed coordinator data."""
    coordinator: BoschK40DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    gateway_unique_id = (
        entry.unique_id
        or coordinator.gateway_info.get("unique_id")
        or coordinator.client.host
    )

    registered_unique_ids: set[str] = set()

    def _get_new_entities() -> list[BoschK40BinarySensor]:
        new_entities: list[BoschK40BinarySensor] = []
        for description in coordinator.active_binary_descriptions:
            cleaned_path = description.resource_id.replace("/", "_").strip("_")
            unique_id = f"{gateway_unique_id}_{cleaned_path}"

            if unique_id in registered_unique_ids:
                continue

            binary_sensor = BoschK40BinarySensor(
                coordinator=coordinator,
                entry=entry,
                description=description,
                gateway_unique_id=gateway_unique_id,
            )

            # Strictly verify that this entity currently delivers valid data
            if binary_sensor.is_on is None:
                continue

            registered_unique_ids.add(unique_id)
            new_entities.append(binary_sensor)
        return new_entities

    initial_entities = _get_new_entities()
    _LOGGER.info("Registered %s Bosch K 40 RF binary sensor entities with valid data", len(initial_entities))
    async_add_entities(initial_entities)

    @callback
    def _async_check_for_new_binary_sensors() -> None:
        new_sensors = _get_new_entities()
        if new_sensors:
            _LOGGER.info("Dynamically registered %s new Bosch K 40 RF binary sensor(s)", len(new_sensors))
            async_add_entities(new_sensors)

    entry.async_on_unload(coordinator.async_add_listener(_async_check_for_new_binary_sensors))


class BoschK40BinarySensor(CoordinatorEntity[BoschK40DataUpdateCoordinator], BinarySensorEntity):
    """Representation of a Bosch K 40 RF binary sensor entity."""

    entity_description: BoschK40BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: BoschK40DataUpdateCoordinator,
        entry: ConfigEntry,
        description: BoschK40BinarySensorEntityDescription,
        gateway_unique_id: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.entry = entry
        self._gateway_unique_id = gateway_unique_id

        cleaned_path = description.resource_id.replace("/", "_").strip("_")
        self._attr_unique_id = f"{gateway_unique_id}_{cleaned_path}"

    @property
    def name(self) -> str | None:
        """Return friendly name with smart hybrid naming."""
        base_name = self.entity_description.name
        if not base_name:
            return None
        if base_name.startswith("HybridManager "):
            base_name = base_name.replace("HybridManager ", "", 1)
        if self.coordinator.is_hybrid_system:
            if self.entity_description.resource_id == "/heatSources/flameStatus":
                return "Flammenstatus Kessel"
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
            gw_sn = (
                str(gw_mod.get("ModuleSerialNumber"))
                if gw_mod and gw_mod.get("ModuleSerialNumber")
                else None
            ) or self.coordinator.gateway_info.get("serial_number")
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
            # In hybrid systems: route Kessel / burner binary sensors to Buderus Kessel
            if self.coordinator.is_hybrid_system:
                if (
                    sub_id == "kessel"
                    or sub_id == "hs1"
                    or self.entity_description.resource_id == "/heatSources/flameStatus"
                ):
                    k_mod = (
                        self.coordinator.get_basic_info_module(hw_ident="MC")
                        or self.coordinator.get_basic_info_module(hw_ident="BC")
                    )
                    k_hw = (k_mod.get("ModuleHwIdentStr") if k_mod else None) or "MC110"
                    k_ver = k_mod.get("Ver") if k_mod else None
                    k_sn = str(k_mod.get("ModuleSerialNumber")) if k_mod and k_mod.get("ModuleSerialNumber") else None
                    return DeviceInfo(
                        identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source_kessel")},
                        name=f"{brand} Kessel ({k_hw})" if k_hw != "Kessel" else f"{brand} Kessel",
                        manufacturer=brand,
                        model=f"Kessel / Brenner ({k_hw})",
                        sw_version=k_ver,
                        serial_number=k_sn,
                        **via_kwargs,
                    )

                # Heat pump specific binary sensors
                is_hp_specific = (
                    sub_id == "hs2"
                    or self.entity_description.resource_id.startswith("/heatSources/hs2/")
                )
                if not is_hp_specific:
                    # HybridManager (HM200) receives all general system / hybrid binary sensors:
                    # fallbackOperation, powerLimitation, silentMode, powerConstraints, etc.
                    hm_mod = (
                        self.coordinator.get_basic_info_module(hw_ident="HM200")
                        or self.coordinator.get_basic_info_module(hw_ident="HM")
                    )
                    hm_hw = (hm_mod.get("ModuleHwIdentStr") if hm_mod else None) or "HM200.2"
                    hm_ver = hm_mod.get("Ver") if hm_mod else None
                    hm_sn = str(hm_mod.get("ModuleSerialNumber")) if hm_mod and hm_mod.get("ModuleSerialNumber") else None
                    return DeviceInfo(
                        identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source_hybman")},
                        name=f"{brand} HybridManager ({hm_hw})" if hm_hw else f"{brand} HybridManager",
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
                k_sn = str(k_mod.get("ModuleSerialNumber")) if k_mod and k_mod.get("ModuleSerialNumber") else None
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
                app_sn = (appliance.get("ProductSerialNumber") or appliance.get("ModuleSerialNumber")) if appliance else None
                return DeviceInfo(
                    identifiers={(DOMAIN, f"{gateway_unique_id}_heat_source")},
                    name=f"{brand} {prod_name}" if prod_name else f"{brand} Wärmeerzeuger",
                    manufacturer=brand,
                    model=prod_name or "Wärmeerzeuger / Wärmepumpe",
                    sw_version=app_ver,
                    serial_number=str(app_sn) if app_sn else None,
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
            mm_sn = str(mm_mod.get("ModuleSerialNumber")) if mm_mod and mm_mod.get("ModuleSerialNumber") else None
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
                serial_number=str(rf_sgtin) if rf_sgtin else None,
                **via_kwargs,
            )

        return DeviceInfo(
            identifiers={(DOMAIN, gateway_unique_id)},
            name=f"{brand} Connect-Key K 40 RF",
            manufacturer=brand,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        res_data = self.coordinator.data.get(self.entity_description.resource_id)
        if not isinstance(res_data, dict):
            return None

        val = res_data.get("value")
        if val is None:
            return None

        # Check invalid sentinels reported in state list
        state_list = res_data.get("state")
        if isinstance(state_list, list):
            for s in state_list:
                if isinstance(s, dict) and "invalid" in s and val == s["invalid"]:
                    return None

        # Direct boolean check
        if isinstance(val, bool):
            return val

        on_values = self.entity_description.on_values
        if isinstance(val, str):
            val_clean = val.strip().lower()
            if not val_clean or val_clean in ("unknown", "unavailable", "null", "none"):
                return None
            if val_clean in ("true", "1", "on", "yes", "active"):
                return True
            if val_clean in ("false", "0", "off", "no", "inactive"):
                return False
            return any(str(o).lower() == val_clean for o in on_values)

        if isinstance(val, (int, float)):
            if val == 1:
                return True
            if val == 0:
                return False

        return val in on_values

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}
        res_data = self.coordinator.data.get(self.entity_description.resource_id)
        if isinstance(res_data, dict):
            if "type" in res_data:
                attrs["resource_type"] = res_data["type"]
            if "allowedValues" in res_data:
                attrs["allowed_values"] = res_data["allowedValues"]
        return attrs
