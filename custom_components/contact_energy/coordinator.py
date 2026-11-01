"""Data update coordinators for Contact Energy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import json
import logging
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_list_statistic_ids,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import async_get as async_get_restore_state
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api import ContactEnergyApi, ContactEnergyError, InvalidAuth
from .const import (
    ACCOUNT_UPDATE_INTERVAL,
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ICP,
    CONF_CONTRACT_ID,
    CONF_FETCH_HISTORY,
    CONF_GAS_RATES,
    CONF_INCLUDE_GST,
    CONF_LEGACY_STATISTIC_IDS,
    CONTRACT_TYPES_GAS,
    CURRENCY,
    DOMAIN,
    GAS_HISTORY_YEARS,
    GAS_UPDATE_INTERVAL,
    GST_RATE,
    REQUEST_DELAY,
    REQUESTS_PER_UPDATE,
    TIMEZONE,
    USAGE_UPDATE_INTERVAL,
)
from .usage import PeriodTotals, UsageCache, gas_month_cost, parse_hourly

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


def parse_date(value: Any) -> date | None:
    """Parse the "29 Oct 2026" dates used by the accounts endpoint."""
    try:
        return datetime.strptime(value, "%d %b %Y").date()
    except (TypeError, ValueError):
        return None


def parse_number(value: Any) -> float | None:
    """Parse numbers that may come as strings."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_register(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Return the first billable register of a contract's first meter."""
    try:
        return contract["devices"][0]["registers"][0]
    except (KeyError, IndexError, TypeError):
        return {}


def first_device(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Return the first meter of a contract."""
    try:
        return contract["devices"][0]
    except (KeyError, IndexError, TypeError):
        return {}


@dataclass
class AccountData:
    """Account details for the configured contract."""

    detail: dict[str, Any]
    electricity: dict[str, Any] | None
    gas: dict[str, Any] | None
    plans: dict[str, str]

    @property
    def plan(self) -> str | None:
        """Plan name of the electricity contract."""
        if self.electricity is None:
            return None
        return self.plans.get(self.electricity.get("id"))

    @property
    def reading_date(self) -> date | None:
        """Date of the last electricity meter reading (billing period start)."""
        return parse_date(
            first_register(self.electricity).get("previousMeterReadingDate")
        )


class ContactEnergyAccountCoordinator(DataUpdateCoordinator[AccountData]):
    """Fetch account, bill and plan details."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: ContactEnergyApi
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} account",
            update_interval=ACCOUNT_UPDATE_INTERVAL,
        )
        self.api = api
        self.account_id: str = entry.data[CONF_ACCOUNT_ID]
        self.contract_id: str = entry.data[CONF_CONTRACT_ID]

    async def _async_update_data(self) -> AccountData:
        try:
            accounts = await self.api.async_get_accounts(self.account_id)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except ContactEnergyError as err:
            raise UpdateFailed(str(err)) from err

        detail = accounts["accountDetail"]
        contracts = detail.get("contracts", [])
        electricity = next(
            (c for c in contracts if str(c.get("id")) == self.contract_id), None
        )
        if electricity is None:
            raise UpdateFailed(
                f"Contract {self.contract_id} is no longer on account {self.account_id}"
            )
        premise = electricity.get("premise", {}).get("id")
        gas_contracts = [
            c for c in contracts if c.get("contractType") in CONTRACT_TYPES_GAS
        ]
        gas = next(
            (c for c in gas_contracts if c.get("premise", {}).get("id") == premise),
            gas_contracts[0] if gas_contracts else None,
        )

        plans: dict[str, str] = self.data.plans if self.data else {}
        try:
            plan_details = await self.api.async_get_plan_details(self.account_id)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except ContactEnergyError as err:
            _LOGGER.debug("Could not fetch plan details: %s", err)
        else:
            plans = {}
            for premise_details in plan_details.get("premises", []):
                for service in premise_details.get("services", []):
                    if not service.get("contract") or not service.get("planDetails"):
                        continue
                    contract_id = str(service["contract"]["contractId"])
                    # A broadband bundle shares the electricity contract id:
                    # the energy plan wins.
                    if contract_id in plans and service.get("serviceType") not in (
                        "ELEC",
                        "GAS",
                    ):
                        continue
                    plans[contract_id] = service["planDetails"].get(
                        "externalPlanDescription"
                    )

        return AccountData(detail, electricity, gas, plans)


@dataclass
class UsageData:
    """Usage totals exposed to the sensors."""

    period: PeriodTotals
    previous_period: PeriodTotals | None
    latest_day: PeriodTotals
    gas_last_month: float | None
    gas_last_month_start: date | None


class ContactEnergyUsageCoordinator(DataUpdateCoordinator[UsageData]):
    """Fetch hourly usage and feed it to the recorder as external statistics."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: ContactEnergyApi,
        account: ContactEnergyAccountCoordinator,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} usage",
            update_interval=USAGE_UPDATE_INTERVAL,
        )
        self.api = api
        self.account = account
        self.icp: str = entry.data[CONF_CONTRACT_ICP]
        self.cache = UsageCache()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._fetch_lock = asyncio.Lock()
        # Month start -> (kWh, cost or None), only for months that have ended.
        self.gas_months: dict[datetime, tuple[float, float | None]] = {}
        self._gas_fetched: datetime | None = None
        self._pending_statistics: str | None = None
        suffix = (
            "" if entry.data.get(CONF_LEGACY_STATISTIC_IDS) else f"_{self.icp.lower()}"
        )
        self.statistic_ids = {
            "paid": f"{DOMAIN}:energy_consumption{suffix}",
            "cost": f"{DOMAIN}:energy_consumption_in_dollars{suffix}",
            "free": f"{DOMAIN}:free_energy_consumption{suffix}",
            "gas": f"{DOMAIN}:gas_consumption{suffix}",
            "gas_cost": f"{DOMAIN}:gas_consumption_in_dollars{suffix}",
        }

    @property
    def fetch_history(self) -> bool:
        """Return whether all available history should be fetched."""
        return self.config_entry.data.get(CONF_FETCH_HISTORY, True)

    @property
    def include_gst(self) -> bool:
        """Return whether costs include GST."""
        return self.config_entry.options.get(CONF_INCLUDE_GST, False)

    @property
    def cost_factor(self) -> float:
        """Multiplier from Contact Energy's costs (excl. GST) to reported costs."""
        return 1 + GST_RATE if self.include_gst else 1.0

    async def async_load(self) -> None:
        """Load the cache and decide whether to re-import all statistics.

        Everything is re-imported when the GST option changed or a statistic
        was deleted (e.g. in Developer tools → Statistics).
        """
        await self._async_load_cache()
        if not self.cache.days:
            return
        if (
            self.cache.costs_include_gst != self.include_gst
            or await self._async_statistics_missing()
        ):
            self._pending_statistics = min(self.cache.days)

    async def _async_statistics_missing(self) -> bool:
        expected = {self.statistic_ids["paid"], self.statistic_ids["cost"]}
        if any(hour[3] > 0 for hours in self.cache.days.values() for hour in hours):
            expected.add(self.statistic_ids["free"])
        existing = {
            item["statistic_id"]
            for item in await async_list_statistic_ids(self.hass, expected)
        }
        if missing := expected - existing:
            _LOGGER.info("Re-importing usage history for %s", sorted(missing))
        return bool(missing)

    async def _async_load_cache(self) -> None:
        """Load the cache, migrating the 1.0.x sensor attributes if needed."""
        if stored := await self._store.async_load():
            self.cache = UsageCache.from_dict(stored)
            return
        if legacy := self._legacy_attributes():
            raw = legacy.get("daily_data")
            try:
                daily = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                daily = None
            if isinstance(daily, dict):
                self.cache = UsageCache.from_legacy_daily(
                    daily, bool(legacy.get("backfill_done"))
                )
                _LOGGER.info(
                    "Migrated %d days of usage from the 1.0.x sensor; "
                    "hourly detail is re-fetched in the background",
                    len(self.cache.days),
                )
                await self._store.async_save(self.cache.as_dict())

    def _legacy_attributes(self) -> dict[str, Any] | None:
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_{self.icp}_usage"
        )
        if entity_id is None:
            return None
        if (state := self.hass.states.get(entity_id)) is None:
            stored = async_get_restore_state(self.hass).last_states.get(entity_id)
            state = stored.state if stored else None
        if state is None or "daily_data" not in state.attributes:
            return None
        return dict(state.attributes)

    async def _async_update_data(self) -> UsageData:
        async with self._fetch_lock:
            try:
                await self._async_fetch_usage()
                await self._async_fetch_gas()
            except InvalidAuth as err:
                raise ConfigEntryAuthFailed from err
            except ContactEnergyError as err:
                raise UpdateFailed(str(err)) from err
            finally:
                self._async_push_statistics()

        reading_date = self.account.data.reading_date if self.account.data else None
        if reading_date and self.cache.add_reading_date(reading_date):
            self._store.async_delay_save(self.cache.as_dict, 10)
        last_month = max(self.gas_months, default=None)
        previous = self.cache.previous_period(reading_date)
        return UsageData(
            self._with_gst(self.cache.totals_since(reading_date)),
            self._with_gst(previous) if previous else None,
            self._with_gst(self.cache.totals_since(self.cache.last_day)),
            self.gas_months[last_month][0] if last_month else None,
            last_month.date() if last_month else None,
        )

    def _with_gst(self, totals: PeriodTotals) -> PeriodTotals:
        return replace(totals, cost=totals.cost * self.cost_factor)

    async def _async_fetch_usage(self) -> None:
        today = dt_util.now(TIMEZONE).date()
        plan = self.cache.plan(today, REQUESTS_PER_UPDATE, self.fetch_history)
        if not plan:
            return
        _LOGGER.debug("Fetching hourly usage for %d day(s): %s", len(plan), plan)
        try:
            for index, day in enumerate(plan):
                if (
                    self.cache.history_done
                    and self.cache.history_cursor
                    and day.isoformat() < self.cache.history_cursor
                ):
                    break  # reached the start of the history in this batch
                if index:
                    await asyncio.sleep(REQUEST_DELAY)
                points = await self.api.async_get_usage(
                    self.account.contract_id,
                    self.account.account_id,
                    "hourly",
                    day,
                    day,
                )
                if self.cache.store_day(day, parse_hourly(points, day), today):
                    key = day.isoformat()
                    if (
                        self._pending_statistics is None
                        or key < self._pending_statistics
                    ):
                        self._pending_statistics = key
        finally:
            self._store.async_delay_save(self.cache.as_dict, 10)

    async def _async_fetch_gas(self) -> None:
        """Fetch monthly gas usage (the API has no daily or hourly gas data)."""
        gas = self.account.data.gas if self.account.data else None
        now = dt_util.utcnow()
        if gas is None or (
            self._gas_fetched and now - self._gas_fetched < GAS_UPDATE_INTERVAL
        ):
            return
        today = dt_util.now(TIMEZONE).date()
        this_month = date(today.year, today.month, 1)
        months: dict[datetime, tuple[float, float | None]] = {}
        # Longer ranges are rejected, so walk back a year at a time until a
        # year without data (the start of the account).
        end = today
        for _ in range(GAS_HISTORY_YEARS):
            start = date(end.year - 1, end.month, 1)
            points = await self.api.async_get_usage(
                str(gas["id"]), self.account.account_id, "monthly", start, end
            )
            found = False
            for point in points:
                value = parse_number(point.get("value"))
                try:
                    month = datetime.fromisoformat(point["date"])
                except (KeyError, TypeError, ValueError):
                    continue
                if value is None or month.date() >= this_month:
                    continue
                months[month] = (value, parse_number(point.get("dollarValue")))
                found = True
            if not found:
                break
            end = start - timedelta(days=1)
        self._gas_fetched = now
        if months != self.gas_months:
            self.gas_months = months
            self._async_push_gas_statistics()

    def _async_push_gas_statistics(self) -> None:
        if not self.gas_months:
            return
        gas_icp = self.account.data.gas["icp"] if self.account.data.gas else self.icp
        rates = self.config_entry.options.get(CONF_GAS_RATES, [])
        starts = sorted(self.gas_months)
        kwh = [self.gas_months[start][0] for start in starts]
        # The API has no gas prices (yet); fall back to the user's rates.
        # Both exclude GST.
        costs: list[float | None] = []
        for start, value in zip(starts, kwh, strict=True):
            cost = self.gas_months[start][1]
            if cost is None:
                cost = gas_month_cost(start.date(), value, rates)
            costs.append(None if cost is None else cost * self.cost_factor)
        series = [
            ("gas", "Gas", UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS, kwh)
        ]
        if any(cost is not None for cost in costs):
            series.append(("gas_cost", "Gas Cost", CURRENCY, None, costs))
        for key, label, unit, unit_class, values in series:
            total = 0.0
            rows = []
            for start, value in zip(starts, values, strict=True):
                total += value or 0.0
                rows.append(StatisticData(start=start, sum=round(total, 3)))
            async_add_external_statistics(
                self.hass,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"Contact Energy - {label} ({gas_icp})",
                    source=DOMAIN,
                    statistic_id=self.statistic_ids[key],
                    unit_class=unit_class,
                    unit_of_measurement=unit,
                ),
                rows,
            )

    def _async_push_statistics(self) -> None:
        if self._pending_statistics is None:
            return
        first_day, self._pending_statistics = self._pending_statistics, None
        rows = self.cache.statistics(first_day)
        if not rows.starts:
            return
        _LOGGER.debug(
            "Updating statistics from %s (%d hours)", first_day, len(rows.starts)
        )
        series = [
            (
                "paid",
                "Electricity",
                UnitOfEnergy.KILO_WATT_HOUR,
                EnergyConverter.UNIT_CLASS,
                rows.paid_kwh,
            ),
            (
                "cost",
                "Electricity Cost",
                CURRENCY,
                None,
                [round(cost * self.cost_factor, 3) for cost in rows.cost],
            ),
        ]
        # Plans without free hours don't get an all-zero free statistic. The
        # sums are cumulative from the first cached day, so once free usage
        # shows up the statistic still starts with the right running total.
        if rows.free_kwh[-1] > 0:
            series.append(
                (
                    "free",
                    "Free Electricity",
                    UnitOfEnergy.KILO_WATT_HOUR,
                    EnergyConverter.UNIT_CLASS,
                    rows.free_kwh,
                )
            )
        for key, label, unit, unit_class, sums in series:
            async_add_external_statistics(
                self.hass,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"Contact Energy - {label} ({self.icp})",
                    source=DOMAIN,
                    statistic_id=self.statistic_ids[key],
                    unit_class=unit_class,
                    unit_of_measurement=unit,
                ),
                [
                    StatisticData(start=start, sum=value)
                    for start, value in zip(rows.starts, sums, strict=True)
                ],
            )
        if self.cache.costs_include_gst != self.include_gst:
            self.cache.costs_include_gst = self.include_gst
            self._store.async_delay_save(self.cache.as_dict, 10)

    async def async_backfill_now(self) -> None:
        """Fetch the next batch right away (used by the button)."""
        await self.async_refresh()

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Cache summary for diagnostics."""
        days = sorted(self.cache.days)
        return {
            "statistic_ids": self.statistic_ids,
            "cached_days": len(days),
            "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None,
            "final_days": len(self.cache.final),
            "days_without_hourly_detail": sum(
                1 for key, hours in self.cache.days.items() if len(hours) == 1
            ),
            "history_cursor": self.cache.history_cursor,
            "history_done": self.cache.history_done,
            "fetch_history": self.fetch_history,
            "latest_day_sample": self.cache.days[days[-1]][:3] if days else [],
            "gas_months": {
                start.date().isoformat(): value
                for start, value in sorted(self.gas_months.items())
            },
        }
