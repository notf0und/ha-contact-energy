"""Tests for the usage cache."""

from __future__ import annotations

from datetime import date, timedelta

from custom_components.contact_energy.const import (
    END_OF_HISTORY_EMPTY_DAYS,
    RECENT_DAYS,
    SHORT_HISTORY_DAYS,
)
from custom_components.contact_energy.usage import (
    UsageCache,
    hours_in_day,
    parse_hourly,
)

from .conftest import hourly

TODAY = date(2026, 10, 30)


def test_hours_in_day_follows_nz_daylight_saving() -> None:
    """Days have 23/25 hours when daylight saving starts/ends."""
    assert hours_in_day(date(2026, 9, 27)) == 23
    assert hours_in_day(date(2026, 4, 5)) == 25
    assert hours_in_day(date(2026, 10, 27)) == 24


def test_parse_hourly_splits_free_usage() -> None:
    """Uncharged usage is reported separately from paid usage."""
    day = date(2026, 10, 27)
    hours = parse_hourly(hourly(day), day)
    assert len(hours) == 24
    assert sum(h[3] for h in hours) == 1.5  # 21:00-23:59 free
    assert round(sum(h[2] for h in hours), 3) == 5.25


def test_daylight_saving_days() -> None:
    """DST days are parsed in order and count as complete."""
    start_dst = date(2026, 9, 27)
    hours = parse_hourly(hourly(start_dst), start_dst)
    assert len(hours) == 23
    assert [h[0] for h in hours] == sorted(h[0] for h in hours)
    cache = UsageCache()
    cache.store_day(start_dst, hours, date(2026, 9, 29))
    assert "2026-09-27" in cache.final


def test_parse_hourly_drops_other_days_and_gaps() -> None:
    """Points of other days or without a value are ignored."""
    day = date(2026, 10, 27)
    points = hourly(day) + hourly(day + timedelta(days=1))
    points[0]["value"] = None
    assert len(parse_hourly(points, day)) == 23


def test_plan_order_and_budget() -> None:
    """Recent days first, then history, within the budget."""
    cache = UsageCache()
    plan = cache.plan(TODAY, 10, fetch_history=True)
    assert plan[:RECENT_DAYS] == [
        TODAY - timedelta(days=i) for i in range(1, RECENT_DAYS + 1)
    ]
    assert plan[RECENT_DAYS] == TODAY - timedelta(days=RECENT_DAYS + 1)
    assert len(plan) == 10


def test_complete_days_are_not_fetched_again() -> None:
    """A complete day is final."""
    cache = UsageCache()
    day = TODAY - timedelta(days=2)
    assert cache.store_day(day, parse_hourly(hourly(day), day), TODAY)
    assert day not in cache.plan(TODAY, 10, fetch_history=True)
    # Same data again: nothing changed.
    assert not cache.store_day(day, parse_hourly(hourly(day), day), TODAY)


def test_history_ends_after_empty_days() -> None:
    """Consecutive empty days mark the start of the history."""
    cache = UsageCache()
    day = TODAY - timedelta(days=RECENT_DAYS + 1)
    for _ in range(END_OF_HISTORY_EMPTY_DAYS):
        cache.store_day(day, [], TODAY)
        day -= timedelta(days=1)
    assert cache.history_done
    assert cache.plan(TODAY, 50, fetch_history=True) == [
        TODAY - timedelta(days=i) for i in range(1, RECENT_DAYS + 1)
    ]


def test_short_history_stops_at_floor() -> None:
    """Without full history only the last few weeks are fetched."""
    plan = UsageCache().plan(TODAY, 500, fetch_history=False)
    assert min(plan) == TODAY - timedelta(days=SHORT_HISTORY_DAYS)


def test_legacy_migration_keeps_running_sums() -> None:
    """Daily lumps from 1.0.x give the same end-of-day sums as hourly data."""
    days = [date(2026, 10, 20), date(2026, 10, 21)]
    legacy = UsageCache.from_legacy_daily(
        {d.isoformat(): {"kwh": 10.5, "dollars": 5.25, "free_kwh": 1.5} for d in days},
        history_done=True,
    )
    hourly_cache = UsageCache()
    for d in days:
        hourly_cache.store_day(d, parse_hourly(hourly(d), d), TODAY)

    legacy_rows = legacy.statistics(days[0].isoformat())
    hourly_rows = hourly_cache.statistics(days[0].isoformat())
    assert legacy_rows.paid_kwh[-1] == hourly_rows.paid_kwh[-1] == 21.0
    assert legacy_rows.free_kwh[-1] == hourly_rows.free_kwh[-1] == 3.0
    assert legacy_rows.cost[-1] == hourly_rows.cost[-1] == 10.5
    # Lumps are re-fetched with hourly detail, newest first.
    plan = legacy.plan(TODAY, 50, fetch_history=True)
    assert plan[RECENT_DAYS:] == list(reversed(days))


def test_totals_since() -> None:
    """Billing period totals start at the reading date."""
    cache = UsageCache()
    for offset in range(5, 9):
        day = TODAY - timedelta(days=offset)
        cache.store_day(day, parse_hourly(hourly(day), day), TODAY)
    totals = cache.totals_since(TODAY - timedelta(days=6))
    assert totals.paid_kwh == 21.0
    assert totals.free_kwh == 3.0
    assert totals.total_kwh == 24.0
    assert totals.last_day == TODAY - timedelta(days=5)
