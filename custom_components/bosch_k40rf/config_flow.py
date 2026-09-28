"""Config flow for Bosch Connect-Key K 40 RF (Buderus MX400) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    BoschK40Client,
    CannotConnect,
    InvalidAuth,
    ProximityError,
    TokenDatabaseFullError,
    clean_host,
    clean_password,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_GATEWAY_BRAND,
    CONF_GATEWAY_MAC,
    CONF_GATEWAY_MODEL,
    CONF_GATEWAY_SERIAL,
    CONF_HOST,
    CONF_LOGIN,
    CONF_PASSWORD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="url")
        ),
        vol.Required(CONF_LOGIN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class BoschK40ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bosch Connect-Key K 40 RF."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_host = user_input[CONF_HOST]
            raw_login = user_input[CONF_LOGIN]
            raw_password = user_input[CONF_PASSWORD]

            host = clean_host(raw_host)
            login = raw_login.strip()
            password = clean_password(raw_password)

            session = async_create_clientsession(self.hass, verify_ssl=False)
            client = BoschK40Client(host, session)

            try:
                auth_data = await client.async_authenticate(login, password)
                access_token = auth_data["access_token"]

                # Fetch gateway metadata for unique_id, brand, and model
                gateway_info = await client.async_get_gateway_info(access_token)
                unique_id = gateway_info.get("unique_id")

                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                brand = gateway_info.get("brand") or "Bosch"
                model = gateway_info.get("model") or "Connect-Key K 40 RF"
                title = f"{brand} {model} ({host})"

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_LOGIN: login,
                        CONF_ACCESS_TOKEN: access_token,
                        CONF_GATEWAY_BRAND: brand,
                        CONF_GATEWAY_MODEL: model,
                        CONF_GATEWAY_MAC: gateway_info.get("mac"),
                        CONF_GATEWAY_SERIAL: gateway_info.get("serial_number"),
                    },
                )

            except ProximityError:
                _LOGGER.warning("Physical proximity unproven during setup for %s", host)
                errors["base"] = "proximity_unproven"
            except InvalidAuth:
                _LOGGER.warning("Invalid credentials during setup for %s", host)
                errors["base"] = "invalid_auth"
            except TokenDatabaseFullError:
                _LOGGER.warning("Gateway token database full on %s", host)
                errors["base"] = "token_database_full"
            except CannotConnect:
                _LOGGER.warning("Cannot connect to %s", host)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error setting up %s: %s", host, err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle initiation of reauthentication."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauthentication confirmation and pairing."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        host = self._reauth_entry.data[CONF_HOST]
        login = self._reauth_entry.data.get(CONF_LOGIN, "")

        if user_input is not None:
            password = clean_password(user_input[CONF_PASSWORD])
            session = async_create_clientsession(self.hass, verify_ssl=False)
            client = BoschK40Client(host, session)

            try:
                auth_data = await client.async_authenticate(login, password)
                new_token = auth_data["access_token"]

                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_ACCESS_TOKEN: new_token,
                    },
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            except ProximityError:
                errors["base"] = "proximity_unproven"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            description_placeholders={"host": host, "login": login},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual reconfiguration to update host, rescan devices/entities, or clean up."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        errors: dict[str, str] = {}
        current_host = entry.data.get(CONF_HOST, "")

        if user_input is not None:
            new_host = clean_host(user_input.get(CONF_HOST, current_host))
            access_token = entry.data.get(CONF_ACCESS_TOKEN, "")
            session = async_create_clientsession(self.hass, verify_ssl=False)
            client = BoschK40Client(new_host, session)

            try:
                gateway_info = await client.async_get_gateway_info(access_token)
                if (
                    entry.unique_id
                    and gateway_info.get("unique_id")
                    and not entry.unique_id.startswith("k40rf_")
                    and not str(gateway_info["unique_id"]).startswith("k40rf_")
                    and gateway_info["unique_id"] != entry.unique_id
                ):
                    errors["base"] = "different_device"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.error("Reconfiguration error connecting to %s: %s", new_host, err)
                errors["base"] = "cannot_connect"

            if not errors:
                old_host = entry.data.get(CONF_HOST, "")
                updates: dict[str, Any] = {"data": {**entry.data, CONF_HOST: new_host}}

                if entry.title.endswith(f"({old_host})"):
                    brand = entry.data.get(CONF_GATEWAY_BRAND) or "Bosch"
                    model = entry.data.get(CONF_GATEWAY_MODEL) or "Connect-Key K 40 RF"
                    updates["title"] = f"{brand} {model} ({new_host})"

                self.hass.config_entries.async_update_entry(entry, **updates)

                # Reload the entry so that the coordinator and platforms re-initialize with the updated host
                await self.hass.config_entries.async_reload(entry.entry_id)

                coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if user_input.get("prune_orphaned") and coordinator is not None:
                    ent_reg = er.async_get(self.hass)
                    existing_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
                    active_unique_ids = {
                        f"{entry.unique_id}_{d.resource_id.replace('/', '_').strip('_')}{f'_{d.value_key}' if d.value_key else ''}"
                        for d in coordinator.active_sensor_descriptions
                    } | {
                        f"{entry.unique_id}_{d.resource_id.replace('/', '_').strip('_')}"
                        for d in coordinator.active_binary_descriptions
                    }
                    for reg_entry in existing_entries:
                        if reg_entry.unique_id not in active_unique_ids:
                            ent_reg.async_remove(reg_entry.entity_id)

                return self.async_abort(reason="reconfigure_successful")

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=user_input.get(CONF_HOST, current_host) if user_input else current_host,
                ): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="url")
                ),
                vol.Optional(
                    "rescan_devices",
                    default=user_input.get("rescan_devices", True) if user_input else True,
                ): bool,
                vol.Optional(
                    "prune_orphaned",
                    default=user_input.get("prune_orphaned", False) if user_input else False,
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            description_placeholders={"host": current_host},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return BoschK40OptionsFlowHandler(config_entry)


class BoschK40OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Bosch K 40 RF."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage integration options."""
        if user_input is not None:
            coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
            if user_input.get("rescan_devices") and coordinator is not None:
                await coordinator.async_discover_endpoints()
                coordinator.async_update_listeners()

            if user_input.get("prune_orphaned") and coordinator is not None:
                ent_reg = er.async_get(self.hass)
                existing_entries = er.async_entries_for_config_entry(ent_reg, self._config_entry.entry_id)
                active_unique_ids = {
                    f"{self._config_entry.unique_id}_{d.resource_id.replace('/', '_').strip('_')}{f'_{d.value_key}' if d.value_key else ''}"
                    for d in coordinator.active_sensor_descriptions
                } | {
                    f"{self._config_entry.unique_id}_{d.resource_id.replace('/', '_').strip('_')}"
                    for d in coordinator.active_binary_descriptions
                }
                for reg_entry in existing_entries:
                    if reg_entry.unique_id not in active_unique_ids:
                        ent_reg.async_remove(reg_entry.entity_id)

            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional("rescan_devices", default=True): bool,
                vol.Optional("prune_orphaned", default=False): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
