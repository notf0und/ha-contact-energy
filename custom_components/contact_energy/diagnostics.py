"""Diagnostics support for Contact Energy."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import ContactEnergyConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "directDebitAccount",
    "supplyAddress",
    "address",
    "shortForm",
    "serialNumber",
    "xcsrfToken",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ContactEnergyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    account = entry.runtime_data.account
    usage = entry.runtime_data.usage
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "account": async_redact_data(asdict(account.data), TO_REDACT)
        if account.data
        else None,
        "usage": {
            **usage.diagnostics,
            "last_update_success": usage.last_update_success,
            "period": asdict(usage.data.period) if usage.data else None,
            "gas_last_month": usage.data.gas_last_month if usage.data else None,
        },
    }
