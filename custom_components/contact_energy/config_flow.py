"""Config flow for Contact Energy integration."""
import asyncio
import logging
import voluptuous as vol
import aiohttp
from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

from .api import ContactEnergyApi, CannotConnect, InvalidAuth, UnknownError
from .const import (
    DOMAIN,
    CONF_USAGE_DAYS,
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ID,
    CONF_CONTRACT_ICP
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_USAGE_DAYS, default=10): cv.positive_int,
    }
)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    _LOGGER.debug("Starting validation for email: %s", data[CONF_EMAIL])
    
    try:
        api = ContactEnergyApi(hass, data[CONF_EMAIL], data[CONF_PASSWORD])
        if not await api.async_login():
            _LOGGER.error("Login failed for email: %s", data[CONF_EMAIL])
            raise InvalidAuth
        
        # Fetch accounts after successful login
        accounts_data = await api.async_get_accounts()
        if not accounts_data or "accountDetail" not in accounts_data:
            _LOGGER.error("No accounts found for email: %s", data[CONF_EMAIL])
            raise UnknownError("No accounts found")

        # Extract available contracts
        account_id = accounts_data["accountDetail"]["id"]
        contracts = []
        for contract in accounts_data["accountDetail"]["contracts"]:
            if contract["contractType"] == 1:  # Electricity contracts only
                contracts.append({
                    "id": contract["id"],
                    "address": contract["premise"]["supplyAddress"]["shortForm"],
                    "account_id": account_id,
                    "icp": contract["icp"]
                })
        
        if not contracts:
            _LOGGER.error("No electricity contracts found for email: %s", data[CONF_EMAIL])
            raise UnknownError("No electricity contracts found")
        
        _LOGGER.info("Successfully authenticated Contact Energy account: %s", data[CONF_EMAIL])
        return {
            "title": f"Contact Energy ({data[CONF_EMAIL]})",
            "email": data[CONF_EMAIL],
            "password": data[CONF_PASSWORD],
            "contracts": contracts
        }
        
    except aiohttp.ClientError as error:
        _LOGGER.error("Connection error during validation: %s", str(error))
        raise CannotConnect from error
    except asyncio.TimeoutError as error:
        _LOGGER.error("Timeout error during validation: %s", str(error))
        raise CannotConnect from error
    except InvalidAuth as error:
        _LOGGER.error("Invalid authentication for email: %s", data[CONF_EMAIL])
        raise error
    except Exception as error:
        _LOGGER.exception("Unexpected error during validation: %s", str(error))
        raise UnknownError from error

class ContactEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Contact Energy."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._current_input = {}
        self._contracts = []
        self._validated_data = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._validated_data = await validate_input(self.hass, user_input)
                self._contracts = self._validated_data["contracts"]
                self._current_input.update(user_input)
                
                # If only one contract is available, skip the selection step
                if len(self._contracts) == 1:
                    contract = self._contracts[0]
                    user_input[CONF_ACCOUNT_ID] = contract["account_id"]
                    user_input[CONF_CONTRACT_ID] = contract["id"]
                    user_input[CONF_CONTRACT_ICP] = contract["icp"]
                    
                    await self.async_set_unique_id(contract["id"])
                    self._abort_if_unique_id_configured()
                    
                    return self.async_create_entry(
                        title=f"{self._validated_data['title']} - {contract['address']}",
                        data=user_input
                    )
                
                return await self.async_step_contract()
                
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as error:
                _LOGGER.exception("Unexpected error in config flow: %s", error)
                errors["base"] = "unknown"

        # Preserve form values
        schema = self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA, self._current_input
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_contract(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle contract selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_contract = next(
                (c for c in self._contracts if c["id"] == user_input[CONF_CONTRACT_ID]),
                None
            )
            if selected_contract:
                self._current_input[CONF_ACCOUNT_ID] = selected_contract["account_id"]
                self._current_input[CONF_CONTRACT_ID] = selected_contract["id"]
                self._current_input[CONF_CONTRACT_ICP] = selected_contract['icp']
                
                await self.async_set_unique_id(selected_contract["id"])
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=f"{self._validated_data['title']} - {selected_contract['address']}",
                    data=self._current_input
                )
            else:
                errors["base"] = "invalid_contract"

        # Create schema for contract selection
        contract_schema = vol.Schema({
            vol.Required(CONF_CONTRACT_ID): vol.In({
                c["id"]: f"{c['id']} - {c['address']}"
                for c in self._contracts
            }),
        })

        return self.async_show_form(
            step_id="contract",
            data_schema=contract_schema,
            errors=errors,
        )