"""DataUpdateCoordinator for Bosch Connect-Key K 40 RF (Buderus MX400)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import BoschK40Client, CannotConnect, InvalidAuth
from .const import (
    CANDIDATE_DEVICES,
    CANDIDATE_DHW_CIRCUITS,
    CANDIDATE_HEAT_SOURCES,
    CANDIDATE_HEATING_CIRCUITS,
    CANDIDATE_SOLAR_CIRCUITS,
    CANDIDATE_VENTILATION_ZONES,
    CANDIDATE_ZONES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import (
    BoschK40BinarySensorEntityDescription,
    BoschK40SensorEntityDescription,
    build_binary_sensors,
    create_dynamic_binary_sensor_description,
    create_dynamic_sensor_description,
    get_all_candidate_sensor_descriptions,
    is_boolean_endpoint,
)

_LOGGER = logging.getLogger(__name__)

# Run dynamic re-discovery every 30 polling cycles (30 minutes)
REDISCOVERY_INTERVAL_CYCLES = 30


class BoschK40DataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch data periodically and dynamically discover new devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: BoschK40Client,
        access_token: str,
        entry: ConfigEntry,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{client.host}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self._access_token = access_token
        self.entry = entry
        self.active_endpoints: set[str] = set()
        self.gateway_info: dict[str, Any] = {}
        self._data: dict[str, Any] = {}
        self._poll_count: int = 0
        self.active_sensor_descriptions: list[BoschK40SensorEntityDescription] = []
        self.active_binary_descriptions: list[BoschK40BinarySensorEntityDescription] = []

    async def async_discover_endpoints(self) -> None:
        """Dynamically discover which heating circuits, zones, and endpoints exist.

        Prevents phantom devices and sensors while automatically adding any new devices
        that are connected to the heating system over time.
        """
        _LOGGER.debug("Starting dynamic endpoint discovery for gateway %s", self.client.host)

        # 1. Fetch gateway metadata
        try:
            self.gateway_info = await self.client.async_get_gateway_info(self._access_token)
        except Exception as err:
            _LOGGER.warning("Could not fetch full gateway info during discovery: %s", err)

        # 2. Concurrently probe existence of circuits and components
        async def _probe_hc(hc: str) -> str | None:
            probe = await self.client.async_get_resource(f"/heatingCircuits/{hc}/overallStatus", self._access_token)
            if probe is None:
                probe = await self.client.async_get_resource(f"/heatingCircuits/{hc}/pumpStatus", self._access_token)
            return hc if probe is not None else None

        async def _probe_dhw(dhw: str) -> str | None:
            probe = await self.client.async_get_resource(f"/dhwCircuits/{dhw}/actualTemp", self._access_token)
            if probe is None:
                probe = await self.client.async_get_resource(f"/dhwCircuits/{dhw}/overallStatus", self._access_token)
            return dhw if probe is not None else None

        async def _probe_hs(hs: str) -> str | None:
            probe = await self.client.async_get_resource(f"/heatSources/{hs}/heatPumpType", self._access_token)
            if probe is None:
                probe = await self.client.async_get_resource(f"/heatSources/{hs}/numberOfStarts", self._access_token)
            return hs if probe is not None else None

        async def _probe_sc(sc: str) -> str | None:
            probe = await self.client.async_get_resource(f"/solarCircuits/{sc}/collectorTemperature", self._access_token)
            return sc if probe is not None else None

        async def _probe_vz(vz: str) -> str | None:
            probe = await self.client.async_get_resource(f"/ventilation/{vz}/sensors/outdoorTemp", self._access_token)
            if probe is None:
                probe = await self.client.async_get_resource(f"/ventilation/{vz}/applianceRunTime", self._access_token)
            return vz if probe is not None else None

        async def _probe_pool() -> str | None:
            probe = await self.client.async_get_resource("/pool/currentTemp", self._access_token)
            return "pool" if probe is not None else None

        async def _probe_signals() -> list[str]:
            signals_probe = await self.client.async_get_resource("/signals", self._access_token)
            sig_eps: list[str] = []
            if isinstance(signals_probe, dict):
                refs = signals_probe.get("references")
                if isinstance(refs, list):
                    for ref in refs:
                        if isinstance(ref, dict) and ref.get("id"):
                            sig_eps.append(ref["id"])
            return sig_eps

        async def _probe_zones() -> list[str]:
            if not CANDIDATE_ZONES:
                return []
            z1_probe, z2_probe = await asyncio.gather(
                self.client.async_get_resource("/zones/zone1/currentRoomSetpoint", self._access_token),
                self.client.async_get_resource("/zones/zone2/currentRoomSetpoint", self._access_token),
                return_exceptions=True,
            )
            confirmed: list[str] = []
            if isinstance(z1_probe, dict):
                confirmed.append("zone1")
            elif await self.client.async_get_resource("/zones/zone1/name", self._access_token) is not None:
                confirmed.append("zone1")
            if isinstance(z2_probe, dict):
                confirmed.append("zone2")
            if not confirmed:
                return []
            consecutive_misses = 0 if len(confirmed) == 2 else 1
            for zone in CANDIDATE_ZONES[2:]:
                p = await self.client.async_get_resource(f"/zones/{zone}/currentRoomSetpoint", self._access_token)
                if p is not None:
                    confirmed.append(zone)
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
                    if consecutive_misses >= 2:
                        break
            return confirmed

        async def _probe_devices() -> list[str]:
            if not CANDIDATE_DEVICES:
                return []
            d1_probe, d2_probe = await asyncio.gather(
                self.client.async_get_resource("/devices/device1/type", self._access_token),
                self.client.async_get_resource("/devices/device2/type", self._access_token),
                return_exceptions=True,
            )
            confirmed: list[str] = []
            if isinstance(d1_probe, dict):
                confirmed.append("device1")
            elif await self.client.async_get_resource("/devices/device1/name", self._access_token) is not None:
                confirmed.append("device1")
            if isinstance(d2_probe, dict):
                confirmed.append("device2")
            if not confirmed:
                return []
            consecutive_misses = 0 if len(confirmed) == 2 else 1
            for dev in CANDIDATE_DEVICES[2:]:
                p = await self.client.async_get_resource(f"/devices/{dev}/type", self._access_token)
                if p is not None:
                    confirmed.append(dev)
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
                    if consecutive_misses >= 2:
                        break
            return confirmed

        (
            hc_results,
            dhw_results,
            hs_results,
            sc_results,
            vz_results,
            pool_result,
            signals_result,
            zones_result,
            devices_result,
        ) = await asyncio.gather(
            asyncio.gather(*[_probe_hc(hc) for hc in CANDIDATE_HEATING_CIRCUITS]),
            asyncio.gather(*[_probe_dhw(dhw) for dhw in CANDIDATE_DHW_CIRCUITS]),
            asyncio.gather(*[_probe_hs(hs) for hs in CANDIDATE_HEAT_SOURCES]),
            asyncio.gather(*[_probe_sc(sc) for sc in CANDIDATE_SOLAR_CIRCUITS]),
            asyncio.gather(*[_probe_vz(vz) for vz in CANDIDATE_VENTILATION_ZONES]),
            _probe_pool(),
            _probe_signals(),
            _probe_zones(),
            _probe_devices(),
        )

        confirmed_circuits: dict[str, list[str]] = {
            "heatingCircuits": [r for r in hc_results if r],
            "dhwCircuits": [r for r in dhw_results if r],
            "heatSources": [r for r in hs_results if r],
            "solarCircuits": [r for r in sc_results if r],
            "ventilation": [r for r in vz_results if r],
            "zones": zones_result,
            "devices": devices_result,
            "pool": [pool_result] if pool_result else [],
        }

        # 3. Assemble all candidate endpoints for testing
        all_sensor_descs = get_all_candidate_sensor_descriptions()
        all_binary_descs = build_binary_sensors()

        candidate_endpoints: set[str] = set()

        for desc in all_sensor_descs + all_binary_descs:
            if getattr(desc, "coordinator_fn", None) is not None:
                continue
            ep = desc.resource_id
            if "/heatingCircuits/hc" in ep:
                if any(f"/{hc}/" in ep for hc in confirmed_circuits["heatingCircuits"]):
                    candidate_endpoints.add(ep)
            elif "/dhwCircuits/dhw" in ep:
                if any(f"/{dhw}/" in ep for dhw in confirmed_circuits["dhwCircuits"]):
                    candidate_endpoints.add(ep)
            elif "/heatSources/hs" in ep:
                if any(f"/{hs}/" in ep for hs in confirmed_circuits["heatSources"]):
                    candidate_endpoints.add(ep)
            elif "/solarCircuits/sc" in ep or "/solarCircuits/" in ep:
                if any(f"/{sc}/" in ep for sc in confirmed_circuits["solarCircuits"]):
                    candidate_endpoints.add(ep)
            elif "/ventilation/zone" in ep or "/ventilation/vz" in ep or "/ventilation/" in ep:
                if any(f"/{vz}/" in ep for vz in confirmed_circuits["ventilation"]):
                    candidate_endpoints.add(ep)
            elif "/zones/zone" in ep or "/zones/" in ep:
                if any(f"/{z}/" in ep for z in confirmed_circuits["zones"]):
                    candidate_endpoints.add(ep)
            elif "/devices/device" in ep or "/devices/" in ep:
                if any(f"/{d}/" in ep for d in confirmed_circuits["devices"]):
                    candidate_endpoints.add(ep)
            elif "/pool/" in ep:
                if confirmed_circuits["pool"]:
                    candidate_endpoints.add(ep)
            elif "{" not in ep:
                candidate_endpoints.add(ep)

        # Add notifications and signals
        candidate_endpoints.add("/notifications")
        candidate_endpoints.update(signals_result)

        # 4. Fetch initial payload for candidate endpoints
        initial_data = await self.client.async_get_all_data(self._access_token, candidate_endpoints)

        # 5. Filter active endpoints (must return dict with id and valid value/values/status)
        valid_endpoints: set[str] = set()
        for ep, item in initial_data.items():
            if isinstance(item, dict) and "id" in item:
                val = item.get("value")
                vals = item.get("values")
                # Even if values is empty list (like in /notifications with no errors), it's valid!
                if (
                    val is not None
                    or vals is not None
                    or item.get("status") is not None
                    or ep == "/notifications"
                    or ep.startswith("/signals/HYBMAN.TimeTillNextCompressor")
                ):
                    valid_endpoints.add(ep)

        # For hybrid managers, always keep compressor start/stop timers active
        if self.is_hybrid_system:
            for ep in (
                "/signals/HYBMAN.TimeTillNextCompressorStart",
                "/signals/HYBMAN.TimeTillNextCompressorStop",
            ):
                valid_endpoints.add(ep)
                if ep not in initial_data or not isinstance(initial_data.get(ep), dict):
                    initial_data[ep] = {"id": ep, "value": 0}

        newly_found = valid_endpoints - self.active_endpoints
        if newly_found:
            _LOGGER.info("Discovered %s new active endpoint(s): %s", len(newly_found), newly_found)

        self.active_endpoints.update(valid_endpoints)
        self._data.update(initial_data)

        # 6. Map active endpoints to entity descriptions (including dynamic descriptions for unknown endpoints)
        matched_sensors: list[BoschK40SensorEntityDescription] = []
        matched_binary: list[BoschK40BinarySensorEntityDescription] = []

        # Known static sensors
        for desc in all_sensor_descs:
            if desc.resource_id in self.active_endpoints:
                matched_sensors.append(desc)
            elif desc.coordinator_fn is not None and desc.resource_id == "/signals/SC.InstallationDate":
                if any(
                    sig in self.active_endpoints
                    for sig in (
                        "/signals/SC.InstallationDate.Day",
                        "/signals/SC.InstallationDate.Month",
                        "/signals/SC.InstallationDate.Year",
                    )
                ):
                    matched_sensors.append(desc)

        # Known static binary sensors
        for desc in all_binary_descs:
            if desc.resource_id in self.active_endpoints:
                matched_binary.append(desc)

        # Dynamic sensors & binary sensors for any active endpoints not covered by static descriptions
        # Exclude unwanted diagnostic / internal endpoints
        ignored_endpoints = {
            "/system/basicInfo",
            "/system/update/report",
            "/system/iSRC/installationStatus",
            "/system/iSRC/supportStatus",
            "/signals/SC.InstallationDate.Day",
            "/signals/SC.InstallationDate.Month",
            "/signals/SC.InstallationDate.Year",
        }
        covered_resources = {d.resource_id for d in matched_sensors + matched_binary} | ignored_endpoints
        for ep in self.active_endpoints:
            if ep not in covered_resources and ep in self._data:
                item = self._data[ep]
                if isinstance(item, dict) and item.get("value") is not None:
                    if is_boolean_endpoint(ep, item):
                        dyn_binary = create_dynamic_binary_sensor_description(ep, item)
                        matched_binary.append(dyn_binary)
                    else:
                        dyn_desc = create_dynamic_sensor_description(ep, item)
                        matched_sensors.append(dyn_desc)

        self.active_sensor_descriptions = matched_sensors
        self.active_binary_descriptions = matched_binary

        _LOGGER.info(
            "Discovery completed: %s active endpoints verified (%s sensors, %s binary sensors)",
            len(self.active_endpoints),
            len(self.active_sensor_descriptions),
            len(self.active_binary_descriptions),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest state for all verified active endpoints."""
        if not self.active_endpoints:
            await self.async_discover_endpoints()
            return self._data

        self._poll_count += 1
        # Periodic background check for newly added devices
        if self._poll_count >= REDISCOVERY_INTERVAL_CYCLES:
            self._poll_count = 0
            try:
                await self.async_discover_endpoints()
                return self._data
            except Exception as err:
                _LOGGER.debug("Background re-discovery error: %s", err)

        if not self.active_endpoints:
            _LOGGER.warning("No active endpoints registered on %s", self.client.host)
            return self._data

        try:
            new_data = await self.client.async_get_all_data(
                self._access_token,
                self.active_endpoints,
            )
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("Access token expired or rejected by gateway.") from err
        except CannotConnect as err:
            raise UpdateFailed(f"Connection error fetching K 40 RF data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating K 40 RF data: {err}") from err

        if not new_data and self.active_endpoints:
            _LOGGER.warning("Gateway %s returned empty payload for all active endpoints", self.client.host)
            return self._data

        self._data.update(new_data)
        return self._data

    def get_value(self, resource_id: str, value_key: str | None = None) -> Any:
        """Safely extract value for a resource from cached data."""
        item = self._data.get(resource_id)
        if not isinstance(item, dict):
            return None
        if value_key:
            return item.get(value_key)
        val = item.get("value")
        if val is not None:
            return val
        return item.get("status")

    def get_basic_info_module(
        self, hw_ident: str | None = None, is_appliance: bool = False
    ) -> dict[str, Any] | None:
        """Find matching module from /system/basicInfo values."""
        basic_info = self._data.get("/system/basicInfo") or self.gateway_info.get("basic_info")
        if not isinstance(basic_info, dict):
            return None
        values = basic_info.get("values") or basic_info.get("raw_values")
        if not isinstance(values, list):
            return None

        for m in values:
            if not isinstance(m, dict):
                continue
            if is_appliance and m.get("ProductName"):
                return m
            if hw_ident and hw_ident.lower() in str(m.get("ModuleHwIdentStr", "")).lower():
                return m
        return None

    @property
    def is_hybrid_system(self) -> bool:
        """Return True if system is a hybrid heating system."""
        sys_type = str(self.get_value("/system/type") or "").lower()
        if "hybrid" in sys_type or sys_type in ("ehybrid", "hybman", "hybridboiler"):
            return True
        if self.get_basic_info_module(hw_ident="HM"):
            return True
        if self.get_basic_info_module(hw_ident="MC") and (
            self.get_basic_info_module(is_appliance=True)
            or self.get_basic_info_module(hw_ident="XCU")
            or self.get_basic_info_module(hw_ident="AW")
        ):
            return True
        if any("HYBMAN" in ep or "hybman" in ep.lower() for ep in self.active_endpoints):
            return True
        hs_active = {ep.split("/")[2] for ep in self.active_endpoints if ep.startswith("/heatSources/hs")}
        if len(hs_active) >= 2:
            return True
        return False

