"""Diagnostics support for Contact Energy.

Besides the integration's state, the dump holds fresh, unmodified responses
from the usage endpoints, so plan types we have never seen (EV, prepay, ...)
can be investigated from a diagnostics file alone.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.util import dt as dt_util

from . import ContactEnergyConfigEntry
from .api import ContactEnergyError
from .const import CONF_CONTRACT_ICP, TIMEZONE

# The ICP is redacted too: the public registry maps it to the address.
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_CONTRACT_ICP,
    "directDebitAccount",
    "supplyAddress",
    "address",
    "shortForm",
    "serialNumber",
    "xcsrfToken",
    "nickname",
    "icp",
}

SAMPLE_DAILY_DAYS = 14
SAMPLE_GAS_MONTHS = 3


async def _sample(request: Awaitable[Any]) -> Any:
    try:
        return await request
    except ContactEnergyError as err:
        return {"error": repr(err)}


async def _api_samples(entry: ContactEnergyConfigEntry) -> dict[str, Any]:
    """Fetch raw responses: plans, the latest day hourly, two weeks daily, gas."""
    account = entry.runtime_data.account
    usage = entry.runtime_data.usage
    api = account.api
    today = dt_util.now(TIMEZONE).date()
    hourly_day: date = usage.cache.last_day or today - timedelta(days=3)

    samples: dict[str, Any] = {
        "plan_details": await _sample(api.async_get_plan_details(account.account_id)),
        "hourly_day": hourly_day,
        "hourly": await _sample(
            api.async_get_usage(
                account.contract_id,
                account.account_id,
                "hourly",
                hourly_day,
                hourly_day,
            )
        ),
        "hourly_cached": usage.cache.days.get(hourly_day.isoformat()),
        "daily": await _sample(
            api.async_get_usage(
                account.contract_id,
                account.account_id,
                "daily",
                today - timedelta(days=SAMPLE_DAILY_DAYS),
                today,
            )
        ),
    }
    if gas := account.data.gas if account.data else None:
        samples["gas_monthly"] = await _sample(
            api.async_get_usage(
                str(gas["id"]),
                account.account_id,
                "monthly",
                (today - timedelta(days=31 * SAMPLE_GAS_MONTHS)).replace(day=1),
                today,
            )
        )
    return samples


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ContactEnergyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    account = entry.runtime_data.account
    usage = entry.runtime_data.usage
    data = usage.data
    icp = entry.data[CONF_CONTRACT_ICP].lower()
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "account": asdict(account.data) if account.data else None,
            "usage": {
                **usage.diagnostics,
                "statistic_ids": {
                    key: statistic_id.replace(icp, REDACTED)
                    for key, statistic_id in usage.statistic_ids.items()
                },
                "last_update_success": usage.last_update_success,
                "period": asdict(data.period) if data else None,
                "previous_period": asdict(data.previous_period)
                if data and data.previous_period
                else None,
                "latest_day": asdict(data.latest_day) if data else None,
                "gas_last_month": data.gas_last_month if data else None,
            },
            "api_samples": await _api_samples(entry),
        },
        TO_REDACT,
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ContactEnergyConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device (the same data: it is all one account)."""
    return {
        "device": device.name,
        **await async_get_config_entry_diagnostics(hass, entry),
    }
