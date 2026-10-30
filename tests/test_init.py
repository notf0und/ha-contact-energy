"""Tests for setup, sensors and statistics."""

from __future__ import annotations

from datetime import date
import json
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.contact_energy.api import InvalidAuth
from custom_components.contact_energy.const import DOMAIN

from .conftest import ELEC_ID, ENTRY_DATA, ICP

STATS = "custom_components.contact_energy.coordinator.async_add_external_statistics"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> list:
    entry.add_to_hass(hass)
    with patch(STATS) as add_stats:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    return add_stats.call_args_list


async def test_setup_creates_sensors_and_statistics(
    hass: HomeAssistant, api, entry
) -> None:
    """Account and usage sensors are created and statistics are imported."""
    calls = await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert (
        hass.states.get("sensor.contact_energy_account_next_bill_amount").state
        == "432.25"
    )
    assert hass.states.get("sensor.contact_energy_account_plan").state == (
        "Good Nights (Monday - Friday)"
    )
    assert hass.states.get("sensor.contact_energy_gas_meter_reading").state == "8078.0"
    usage = hass.states.get("sensor.contact_energy_electricity_usage")
    assert usage.attributes["period_start"] == date(2026, 10, 25)
    assert float(usage.state) >= 0

    ids = {call.args[1]["statistic_id"] for call in calls}
    suffix = ICP.lower()
    assert ids == {
        f"{DOMAIN}:energy_consumption_{suffix}",
        f"{DOMAIN}:energy_consumption_in_dollars_{suffix}",
        f"{DOMAIN}:free_energy_consumption_{suffix}",
    }
    paid = next(
        c.args[2]
        for c in calls
        if c.args[1]["statistic_id"].startswith(f"{DOMAIN}:energy_consumption_0")
    )
    sums = [row["sum"] for row in paid]
    assert sums == sorted(sums)
    assert len({row["start"] for row in paid}) == len(paid)


async def test_no_gas_contract(hass: HomeAssistant, api, entry) -> None:
    """Gas sensors are only created with a gas contract."""
    from .conftest import accounts

    api["accounts"].side_effect = lambda *_: accounts(gas=False)
    await _setup(hass, entry)
    assert hass.states.get("sensor.contact_energy_gas_meter_reading") is None


async def test_auth_failure_starts_reauth(hass: HomeAssistant, api, entry) -> None:
    """A rejected password starts the reauth flow."""
    api["accounts"].side_effect = InvalidAuth
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_migration_from_1_0(hass: HomeAssistant, api) -> None:
    """1.0.x entries keep their statistic ids and cached usage."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ELEC_ID, data=ENTRY_DATA, version=1, minor_version=1
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_{ICP}_usage",
        suggested_object_id="contact_energy_usage",
        config_entry=entry,
    )
    daily = {"2026-01-10": {"kwh": 10.0, "dollars": 4.0, "free_kwh": 2.0}}
    mock_restore_cache(
        hass,
        [
            State(
                "sensor.contact_energy_usage",
                "0",
                {"daily_data": json.dumps(daily), "backfill_done": True},
            )
        ],
    )
    with patch(STATS) as add_stats:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.minor_version == 2
    assert entry.data["legacy_statistic_ids"] is True
    ids = {call.args[1]["statistic_id"] for call in add_stats.call_args_list}
    assert f"{DOMAIN}:energy_consumption" in ids
    usage = entry.runtime_data.usage
    assert "2026-01-10" in usage.cache.days
    assert usage.cache.history_done
    # The 1.0.x entity id is kept.
    assert hass.states.get("sensor.contact_energy_usage") is not None
