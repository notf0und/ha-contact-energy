"""Config flow for the Contact Energy integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import CannotConnect, ContactEnergyApi, InvalidAuth
from .const import (
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ICP,
    CONF_CONTRACT_ID,
    CONF_FETCH_HISTORY,
    CONTRACT_TYPE_ELECTRICITY,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
        vol.Optional(CONF_FETCH_HISTORY, default=True): bool,
    }
)


async def _async_electricity_contracts(api: ContactEnergyApi) -> list[dict[str, str]]:
    """Return every electricity contract of every account of the login."""
    accounts = await api.async_get_accounts()
    account_ids = [
        str(summary["id"]) for summary in accounts.get("accountsSummary", [])
    ] or [str(accounts["accountDetail"]["id"])]

    contracts: list[dict[str, str]] = []
    for account_id in account_ids:
        if str(accounts["accountDetail"]["id"]) != account_id:
            accounts = await api.async_get_accounts(account_id)
        detail = accounts["accountDetail"]
        contracts.extend(
            {
                CONF_ACCOUNT_ID: str(detail["id"]),
                CONF_CONTRACT_ID: str(contract["id"]),
                CONF_CONTRACT_ICP: contract["icp"],
                "address": contract.get("premise", {})
                .get("supplyAddress", {})
                .get("shortForm", contract["icp"]),
            }
            for contract in detail.get("contracts", [])
            if contract.get("contractType") == CONTRACT_TYPE_ELECTRICITY
        )
    return contracts


class ContactEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Contact Energy."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}
        self._contracts: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = ContactEnergyApi(
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                self._contracts = await _async_electricity_contracts(api)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                if not self._contracts:
                    return self.async_abort(reason="no_electricity_contracts")
                self._user_input = user_input
                if len(self._contracts) == 1:
                    return await self._async_create_entry(self._contracts[0])
                return await self.async_step_contract()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_contract(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the electricity contract (ICP) when the login has several."""
        if user_input is not None:
            contract = next(
                c
                for c in self._contracts
                if c[CONF_CONTRACT_ID] == user_input[CONF_CONTRACT_ID]
            )
            return await self._async_create_entry(contract)

        return self.async_show_form(
            step_id="contract",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONTRACT_ID): vol.In(
                        {
                            c[
                                CONF_CONTRACT_ID
                            ]: f"{c['address']} (ICP {c[CONF_CONTRACT_ICP]})"
                            for c in self._contracts
                        }
                    )
                }
            ),
        )

    async def _async_create_entry(self, contract: dict[str, str]) -> ConfigFlowResult:
        await self.async_set_unique_id(contract[CONF_CONTRACT_ID])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"{NAME} - {contract['address']}",
            data={
                **self._user_input,
                CONF_ACCOUNT_ID: contract[CONF_ACCOUNT_ID],
                CONF_CONTRACT_ID: contract[CONF_CONTRACT_ID],
                CONF_CONTRACT_ICP: contract[CONF_CONTRACT_ICP],
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the password was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            api = ContactEnergyApi(
                async_get_clientsession(self.hass),
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                await api.async_login()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change whether all history is fetched."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates={CONF_FETCH_HISTORY: user_input[CONF_FETCH_HISTORY]},
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FETCH_HISTORY,
                        default=entry.data.get(CONF_FETCH_HISTORY, True),
                    ): bool,
                }
            ),
        )
