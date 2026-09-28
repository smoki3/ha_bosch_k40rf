"""API Client for Bosch Connect-Key K 40 RF (Buderus MX400) Local REST API."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Iterable

import aiohttp

from .const import (
    AUTH_PORT,
    DATA_PORT,
    DEFAULT_CLIENT_NAME,
)

_LOGGER = logging.getLogger(__name__)


class BoschK40Error(Exception):
    """Base exception for Bosch K40 RF API."""


class CannotConnect(BoschK40Error):
    """Exception raised when connection to gateway fails."""


class InvalidAuth(BoschK40Error):
    """Exception raised when authentication fails (HTTP 400 or 401)."""


class ProximityError(BoschK40Error):
    """Exception raised when physical proximity was unproven (HTTP 412).

    The user must press the WLAN and Wireless buttons simultaneously for 1 second.
    """


class TokenDatabaseFullError(BoschK40Error):
    """Exception raised when token database on gateway is full (HTTP 507)."""


def clean_host(host: str) -> str:
    """Clean and normalize host string."""
    host = host.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0]
    # Remove port if user appended :9442 or :9443
    if ":" in host:
        host = host.split(":")[0]
    return host.rstrip("/")


def clean_password(password: str) -> str:
    """Remove hyphens and whitespace from password as required by gateway."""
    return password.replace("-", "").strip()


def normalize_mac(mac: str | None) -> str | None:
    """Format MAC address to uppercase colon-separated string."""
    if not mac:
        return None
    cleaned = re.sub(r"[^0-9a-fA-F]", "", mac).upper()
    if len(cleaned) == 12:
        return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))
    return mac.strip()


class BoschK40Client:
    """Client for communicating with the Bosch K 40 RF gateway."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        """Initialize the client."""
        self._host = clean_host(host)
        self._session = session

    @property
    def host(self) -> str:
        """Return the host address."""
        return self._host

    async def async_authenticate(
        self,
        login: str,
        password: str,
        client_name: str = DEFAULT_CLIENT_NAME,
    ) -> dict[str, Any]:
        """Authenticate with the gateway on port 9442 and retrieve an access token.

        Requires physical button press (WLAN + Wireless for 1s) within 5 minutes.
        """
        clean_user = login.strip()
        clean_pass = clean_password(password)
        url = f"https://{self._host}:{AUTH_PORT}/auth/token"

        payload = {
            "grant_type": "password",
            "username": clean_user,
            "password": clean_pass,
            "client_name": client_name,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        _LOGGER.debug("Requesting auth token from %s with client_name=%s", url, client_name)

        try:
            async with self._session.post(
                url,
                data=payload,
                headers=headers,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                status = response.status
                text = await response.text()
                _LOGGER.debug("Auth response status %s: %s", status, text)

                if status == 200:
                    try:
                        data = await response.json()
                    except Exception as err:
                        raise CannotConnect(f"Invalid JSON in auth response: {err}") from err

                    if "access_token" not in data:
                        raise CannotConnect("Auth response did not contain access_token")
                    return data

                if status == 412:
                    # Physical proximity unproven
                    raise ProximityError(
                        "Physical proximity unproven (HTTP 412). "
                        "Please press the WLAN and Wireless buttons for 1 second."
                    )

                if status in (400, 401, 403):
                    raise InvalidAuth(f"Authentication failed with status {status}: {text}")

                if status == 507:
                    raise TokenDatabaseFullError(
                        "Token database on gateway is full (HTTP 507). "
                        "Unused tokens must be revoked."
                    )

                raise CannotConnect(f"Unexpected status code {status} during authentication: {text}")

        except (ProximityError, InvalidAuth, TokenDatabaseFullError):
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.error("Connection error while authenticating to %s: %s", url, err)
            raise CannotConnect(f"Connection failed: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error while authenticating to %s: %s", url, err)
            raise CannotConnect(f"Unexpected error: {err}") from err

    async def async_get_resource(
        self,
        endpoint: str,
        access_token: str,
    ) -> dict[str, Any] | None:
        """Get a single resource from the data API on port 9443."""
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"

        url = f"https://{self._host}:{DATA_PORT}{endpoint}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        try:
            async with self._session.get(
                url,
                headers=headers,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    try:
                        return await response.json()
                    except Exception as err:
                        _LOGGER.debug("Failed to decode JSON from %s: %s", url, err)
                        return None

                if response.status == 404:
                    _LOGGER.debug("Resource %s returned 404 Not Found", endpoint)
                    return None

                if response.status in (401, 403):
                    _LOGGER.warning("Access token rejected for %s (status %s)", url, response.status)
                    raise InvalidAuth("Access token rejected by gateway.")

                _LOGGER.debug("Resource %s returned status %s", endpoint, response.status)
                return None

        except InvalidAuth:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Connection error reading %s: %s", url, err)
            raise CannotConnect(f"Failed to connect to {url}: {err}") from err

    async def async_get_gateway_info(self, access_token: str) -> dict[str, Any]:
        """Fetch basic gateway metadata to determine identity, brand, model, and serial/MAC."""
        info: dict[str, Any] = {
            "brand": "Bosch",
            "model": "Connect-Key K 40 RF",
            "firmware": None,
            "hardware": None,
            "mac": None,
            "serial_number": None,
            "unique_id": None,
        }

        # Concurrently fetch metadata endpoints
        brand_data, fw_data, hw_data, eth_mac, wifi_mac, basic_info = await asyncio.gather(
            self.async_get_resource("/gateway/brand", access_token),
            self.async_get_resource("/gateway/versionFirmware", access_token),
            self.async_get_resource("/gateway/versionHardware", access_token),
            self.async_get_resource("/gateway/eth/mac", access_token),
            self.async_get_resource("/gateway/wifi/mac", access_token),
            self.async_get_resource("/system/basicInfo", access_token),
            return_exceptions=True,
        )

        # 1. Evaluate brand
        if isinstance(brand_data, dict) and brand_data.get("value"):
            info["brand"] = str(brand_data["value"]).strip()

        # Update model name based on brand if applicable
        if info["brand"].lower() == "buderus":
            info["model"] = "MX400"

        # 2. Evaluate firmware & hardware versions
        if isinstance(fw_data, dict) and fw_data.get("value"):
            info["firmware"] = str(fw_data["value"]).strip()

        if isinstance(hw_data, dict) and hw_data.get("value"):
            info["hardware"] = str(hw_data["value"]).strip()

        # 3. Evaluate MAC address (try ethernet then wifi)
        mac_raw = None
        if isinstance(eth_mac, dict) and eth_mac.get("value"):
            mac_raw = str(eth_mac["value"]).strip()
        elif isinstance(wifi_mac, dict) and wifi_mac.get("value"):
            mac_raw = str(wifi_mac["value"]).strip()

        if mac_raw:
            info["mac"] = normalize_mac(mac_raw)

        # 4. Evaluate system basic info (for serial and module identification)
        if isinstance(basic_info, dict):
            info["basic_info"] = basic_info
            gateway_id = basic_info.get("gatewayId")
            if gateway_id:
                info["serial_number"] = str(gateway_id)

            # Search in values list for K40RF module
            values = basic_info.get("values")
            if isinstance(values, list):
                for module in values:
                    if not isinstance(module, dict):
                        continue
                    if module.get("ModuleHwIdentStr") in ("K40RF", "K30RF"):
                        mod_sn = module.get("ModuleSerialNumber")
                        if mod_sn:
                            info["serial_number"] = str(mod_sn)
                        mod_ver = module.get("Ver")
                        if mod_ver and not info["firmware"]:
                            info["firmware"] = str(mod_ver)

        # 5. Determine unique ID
        if info["mac"]:
            info["unique_id"] = info["mac"].replace(":", "").upper()
        elif info["serial_number"]:
            info["unique_id"] = str(info["serial_number"]).strip()
        else:
            info["unique_id"] = f"k40rf_{self._host.replace('.', '_')}"

        return info

    async def async_get_all_data(
        self,
        access_token: str,
        endpoints: Iterable[str],
        max_concurrency: int = 10,
    ) -> dict[str, Any]:
        """Fetch multiple resources concurrently with bounded concurrency.

        Ignores 404 or missing endpoints cleanly.
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        results: dict[str, Any] = {}

        async def _fetch(endpoint: str) -> None:
            async with semaphore:
                try:
                    res = await self.async_get_resource(endpoint, access_token)
                    if res is not None:
                        results[endpoint] = res
                except InvalidAuth:
                    raise
                except CannotConnect:
                    # Ignore single transient resource connection failure in batch
                    _LOGGER.debug("Resource %s could not be fetched", endpoint)

        tasks = [_fetch(ep) for ep in endpoints]
        await asyncio.gather(*tasks)
        return results
