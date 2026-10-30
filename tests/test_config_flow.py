"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.contact_energy.api import InvalidAuth
from custom_components.contact_energy.const import DOMAIN

from .conftest import ACCOUNT_ID, ELEC_ID, ICP, accounts, contract

USER_INPUT = {"email": "user@example.com", "password": "secret", "fetch_history": True}


async def test_user_flow_single_contract(hass: HomeAssistant, api) -> None:
    """One electricity contract: the entry is created straight away."""
    with patch("custom_components.contact_energy.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == ELEC_ID
    assert result["data"] == {
        **USER_INPUT,
        "account_id": ACCOUNT_ID,
        "contract_id": ELEC_ID,
        "contract_icp": ICP,
    }
    assert result["result"].minor_version == 2


async def test_user_flow_picks_contract(hass: HomeAssistant, api) -> None:
    """Several electricity contracts: the user picks one."""
    data = accounts()
    data["accountDetail"]["contracts"].append(
        contract("1300000003", "0000999999ZZ9ZZ", 1, "kWH")
    )
    api["accounts"].side_effect = None
    api["accounts"].return_value = data
    with patch("custom_components.contact_energy.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        assert result["step_id"] == "contract"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"contract_id": "1300000003"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["contract_icp"] == "0000999999ZZ9ZZ"


async def test_user_flow_invalid_auth(hass: HomeAssistant, api) -> None:
    """A rejected password shows an error."""
    api["accounts"].side_effect = InvalidAuth
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth(hass: HomeAssistant, api, entry) -> None:
    """Re-authentication stores the new password."""
    entry.add_to_hass(hass)
    with patch("custom_components.contact_energy.async_setup_entry", return_value=True):
        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new-secret"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-secret"


async def test_reauth_rejected(hass: HomeAssistant, api, entry) -> None:
    """A wrong password during re-authentication shows an error."""
    entry.add_to_hass(hass)
    api["login"].side_effect = InvalidAuth
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert isinstance(api["login"], AsyncMock)


async def test_options_gas_rates(hass: HomeAssistant, api, entry) -> None:
    """Gas rates are kept per month; clearing them removes the gas cost."""
    entry.add_to_hass(hass)
    with patch("custom_components.contact_energy.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"gas_price": 0.11362, "gas_daily_charge": 2.71}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["include_gst"] is False
        rates = entry.options["gas_rates"]
        assert len(rates) == 1
        assert rates[0]["price"] == 0.11362

        # A second change in the same month replaces the rate.
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"include_gst": True, "gas_price": 0.12}
        )
        assert entry.options["include_gst"] is True
        assert [r["price"] for r in entry.options["gas_rates"]] == [0.12]
        assert entry.options["gas_rates"][0]["daily"] == 0.0

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )
        assert entry.options["gas_rates"] == []
