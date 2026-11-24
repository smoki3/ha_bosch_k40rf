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
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util import dt as dt_util

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
    CONF_TOKEN_ID,
    DEFAULT_CLIENT_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _async_resolve_current_token_id(
    client: BoschK40Client,
    access_token: str,
    auth_data: dict[str, Any],
) -> str | None:
    """Determine the token_id of a newly created token (best-effort)."""
    direct_id = auth_data.get("token_id") if auth_data.get("token_id") is not None else auth_data.get("id")
    if direct_id is not None:
        return str(direct_id)
    try:
        tokens = await client.async_list_tokens(access_token)
    except Exception:
        return None
    if not tokens:
        return None
    for tok in tokens:
        if tok.get("is_current"):
            return tok["token_id"]
    matching = [t for t in tokens if t.get("client_name") == DEFAULT_CLIENT_NAME] or tokens
    newest = max(
        matching,
        key=lambda t: (
            t.get("created_at") or 0,
            int(t["token_id"]) if str(t["token_id"]).isdigit() else 0,
        ),
    )
    return newest["token_id"]

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
        self._discovered_host: str | None = None
        self._discovered_model: str | None = None
        self._discovered_brand: str | None = None

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
                token_id = await _async_resolve_current_token_id(client, access_token, auth_data)

                # Fetch gateway metadata for unique_id, brand, and model
                gateway_info = await client.async_get_gateway_info(access_token)
                unique_id = gateway_info.get("unique_id")

                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                brand = gateway_info.get("brand") or "Bosch"
                model = gateway_info.get("model") or "Connect-Key K 40 RF"
                title = f"{brand} {model} ({host})"

                entry_data = {
                    CONF_HOST: host,
                    CONF_LOGIN: login,
                    CONF_ACCESS_TOKEN: access_token,
                    CONF_GATEWAY_BRAND: brand,
                    CONF_GATEWAY_MODEL: model,
                    CONF_GATEWAY_MAC: gateway_info.get("mac"),
                    CONF_GATEWAY_SERIAL: gateway_info.get("serial_number"),
                }
                if token_id is not None:
                    entry_data[CONF_TOKEN_ID] = token_id

                return self.async_create_entry(
                    title=title,
                    data=entry_data,
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

        schema_dict: dict[Any, Any] = {}
        if self._discovered_host:
            schema_dict[vol.Required(CONF_HOST, default=self._discovered_host)] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="url")
            )
        else:
            schema_dict[vol.Required(CONF_HOST)] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="url")
            )
        schema_dict[vol.Required(CONF_LOGIN)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        )
        schema_dict[vol.Required(CONF_PASSWORD)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle zeroconf discovery for Bosch Connect-Key K 40 RF / Buderus MX400."""
        host = discovery_info.host
        self._discovered_host = host

        # Properties may contain model, brand, uuid
        props = discovery_info.properties
        self._discovered_model = props.get("model")
        self._discovered_brand = props.get("brand")
        uuid = props.get("uuid")

        if uuid:
            await self.async_set_unique_id(str(uuid))
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        # Check if already configured with this host
        for entry in self._async_current_entries():
            if entry.data.get(CONF_HOST) == host:
                return self.async_abort(reason="already_configured")

        brand = self._discovered_brand or "Bosch"
        model = self._discovered_model or "Connect-Key K 40 RF"
        self.context["title_placeholders"] = {"name": f"{brand} {model} ({host})"}

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery of a Bosch / Buderus gateway and collect credentials."""
        errors: dict[str, str] = {}
        assert self._discovered_host is not None
        host = self._discovered_host

        if user_input is not None:
            raw_login = user_input[CONF_LOGIN]
            raw_password = user_input[CONF_PASSWORD]

            login = raw_login.strip()
            password = clean_password(raw_password)

            session = async_create_clientsession(self.hass, verify_ssl=False)
            client = BoschK40Client(host, session)

            try:
                auth_data = await client.async_authenticate(login, password)
                access_token = auth_data["access_token"]
                token_id = await _async_resolve_current_token_id(client, access_token, auth_data)

                # Fetch gateway metadata for unique_id, brand, and model
                gateway_info = await client.async_get_gateway_info(access_token)
                unique_id = gateway_info.get("unique_id")

                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                brand = gateway_info.get("brand") or self._discovered_brand or "Bosch"
                model = gateway_info.get("model") or self._discovered_model or "Connect-Key K 40 RF"
                title = f"{brand} {model} ({host})"

                entry_data = {
                    CONF_HOST: host,
                    CONF_LOGIN: login,
                    CONF_ACCESS_TOKEN: access_token,
                    CONF_GATEWAY_BRAND: brand,
                    CONF_GATEWAY_MODEL: model,
                    CONF_GATEWAY_MAC: gateway_info.get("mac"),
                    CONF_GATEWAY_SERIAL: gateway_info.get("serial_number"),
                }
                if token_id is not None:
                    entry_data[CONF_TOKEN_ID] = token_id

                return self.async_create_entry(
                    title=title,
                    data=entry_data,
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

        schema = vol.Schema(
            {
                vol.Required(CONF_LOGIN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

        model_name = f"{self._discovered_brand or 'Bosch'} {self._discovered_model or 'Connect-Key K 40 RF'}"
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=schema,
            description_placeholders={"host": host, "model": model_name},
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
                new_token_id = await _async_resolve_current_token_id(client, new_token, auth_data)

                new_data = {
                    **self._reauth_entry.data,
                    CONF_ACCESS_TOKEN: new_token,
                }
                if new_token_id is not None:
                    new_data[CONF_TOKEN_ID] = new_token_id

                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data=new_data,
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
        self._tokens: list[dict[str, Any]] = []

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

            if user_input.get("manage_tokens"):
                return await self.async_step_manage_tokens()

            return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Optional("rescan_devices", default=True): bool,
                vol.Optional("prune_orphaned", default=False): bool,
                vol.Optional("manage_tokens", default=False): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_manage_tokens(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List and revoke old tokens stored on the gateway."""
        errors: dict[str, str] = {}
        host = self._config_entry.data.get(CONF_HOST, "")
        access_token = self._config_entry.data.get(CONF_ACCESS_TOKEN, "")

        session = async_create_clientsession(self.hass, verify_ssl=False)
        client = BoschK40Client(host, session)

        if user_input is not None:
            selected_ids: list[str] = user_input.get("tokens_to_revoke", [])
            if not selected_ids:
                return self.async_create_entry(title="", data={})

            token_usage_map = {
                tok["token_id"]: tok.get("usage_type", "private")
                for tok in self._tokens
            }
            all_revoked = True
            for token_id in selected_ids:
                ok = await client.async_revoke_token_by_id(
                    access_token,
                    token_id,
                    token_usage_map.get(token_id, "private"),
                )
                if not ok:
                    all_revoked = False

            if all_revoked:
                return self.async_create_entry(title="", data={})
            errors["base"] = "revoke_failed"

        try:
            self._tokens = await client.async_list_tokens(access_token)
        except InvalidAuth:
            self._tokens = []
            errors["base"] = "invalid_auth"
        except CannotConnect:
            self._tokens = []
            errors["base"] = "cannot_connect"
        except Exception as err:
            _LOGGER.debug("Unexpected error loading token list from %s: %s", host, err)
            self._tokens = []
            errors["base"] = "cannot_connect"

        used_slots = len(self._tokens)
        saved_token_id = self._config_entry.data.get(CONF_TOKEN_ID)
        current_token_id: str | None = str(saved_token_id) if saved_token_id is not None else None

        if current_token_id is None:
            for tok in self._tokens:
                if tok.get("is_current"):
                    current_token_id = tok["token_id"]
                    break

        # Fallback heuristic for existing entries without saved token_id:
        # match token created_at against config entry created_at / modified_at (±120s)
        if current_token_id is None and len(self._tokens) > 1:
            ref_timestamps: list[float] = []
            for dt_attr in ("created_at", "modified_at"):
                dt_obj = getattr(self._config_entry, dt_attr, None)
                if dt_obj is not None and hasattr(dt_obj, "timestamp"):
                    ref_timestamps.append(dt_obj.timestamp())
            if ref_timestamps:
                matched_ids = [
                    tok["token_id"]
                    for tok in self._tokens
                    if tok.get("created_at") is not None
                    and any(abs(tok["created_at"] - ref_ts) <= 120 for ref_ts in ref_timestamps)
                ]
                if len(matched_ids) == 1:
                    current_token_id = matched_ids[0]

        sorted_tokens = sorted(
            self._tokens,
            key=lambda t: (
                t.get("created_at") or 0,
                int(t["token_id"]) if str(t["token_id"]).isdigit() else 0,
            ),
        )

        options: list[SelectOptionDict] = []
        if len(sorted_tokens) > 1:
            for tok in sorted_tokens:
                if current_token_id is not None and tok["token_id"] == current_token_id:
                    continue
                created_at = tok.get("created_at")
                if created_at is not None:
                    dt_local = dt_util.as_local(dt_util.utc_from_timestamp(created_at))
                    label = f"ID {tok['token_id']} – {tok['client_name']} ({dt_local.strftime('%d.%m.%Y %H:%M')})"
                else:
                    label = f"ID {tok['token_id']} – {tok['client_name']}"
                options.append(
                    SelectOptionDict(
                        value=tok["token_id"],
                        label=label,
                    )
                )

        if options:
            schema = vol.Schema(
                {
                    vol.Optional("tokens_to_revoke", default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            )
        else:
            schema = vol.Schema({})
            if not errors:
                errors["base"] = "no_other_tokens"

        return self.async_show_form(
            step_id="manage_tokens",
            data_schema=schema,
            description_placeholders={
                "host": host,
                "used_slots": str(used_slots),
                "max_slots": "10",
            },
            errors=errors,
        )
