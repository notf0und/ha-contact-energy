"""Hourly usage cache: what to fetch next, and the totals derived from it.

Kept free of Home Assistant imports so it can be unit tested on its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from .const import (
    END_OF_HISTORY_EMPTY_DAYS,
    FINAL_AFTER_DAYS,
    RECENT_DAYS,
    SHORT_HISTORY_DAYS,
    TIMEZONE,
)

# One hour of usage: [start (ISO 8601, local offset), kWh, cost, uncharged kWh]
Hour = list[Any]


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _same_day_in(year: int, month: int, day: int) -> date:
    """Return ``day`` of the given month, clamped to the month's length."""
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def hours_in_day(day: date) -> int:
    """Return 23, 24 or 25 depending on daylight saving changes."""
    start = datetime.combine(day, time(), TIMEZONE).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), TIMEZONE).astimezone(UTC)
    return round((end - start).total_seconds() / 3600)


def parse_hourly(points: list[dict[str, Any]], day: date) -> list[Hour]:
    """Convert hourly API points for ``day`` into cache rows."""
    hours: dict[datetime, Hour] = {}
    for point in points:
        if point.get("value") is None:
            continue
        try:
            start = datetime.fromisoformat(point["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if start.astimezone(TIMEZONE).date() != day:
            continue
        kwh = _number(point["value"])
        cost = _number(point.get("dollarValue"))
        if "unchargedValue" in point:
            free = _number(point["unchargedValue"])
        else:
            # Older responses only had offpeakValue; it is free when not charged.
            offpeak = _number(point.get("offpeakValue"))
            free = offpeak if _number(point.get("offpeakDollarValue")) == 0 else 0.0
        hours[start.astimezone(UTC)] = [start.isoformat(), kwh, cost, min(free, kwh)]
    return [hours[start] for start in sorted(hours)]


def gas_month_cost(
    month: date, kwh: float, rates: list[dict[str, Any]]
) -> float | None:
    """Return a month's gas cost from the user's rates (None without rates).

    Each rate is ``{"from": "YYYY-MM", "price": per kWh, "daily": per day}``;
    the oldest one also covers the months before it.
    """
    if not rates:
        return None
    key = month.strftime("%Y-%m")
    rate = rates[0]
    for candidate in rates:
        if candidate["from"] <= key:
            rate = candidate
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    days = (next_month - month.replace(day=1)).days
    return kwh * _number(rate.get("price")) + days * _number(rate.get("daily"))


@dataclass
class PeriodTotals:
    """Usage totals from a start day up to the latest data."""

    start: date | None
    paid_kwh: float
    free_kwh: float
    cost: float
    last_day: date | None
    end: date | None = None
    estimated_start: bool = False

    @property
    def total_kwh(self) -> float:
        """Paid plus free usage."""
        return self.paid_kwh + self.free_kwh


@dataclass
class StatisticsRows:
    """Cumulative hourly sums, ready for the recorder."""

    starts: list[datetime]
    paid_kwh: list[float]
    cost: list[float]
    free_kwh: list[float]


class UsageCache:
    """Hourly usage per local day plus the history-fetching state."""

    def __init__(self) -> None:
        """Initialize an empty cache."""
        self.days: dict[str, list[Hour]] = {}
        # Days that will not be fetched again.
        self.final: set[str] = set()
        # Oldest day already requested while walking back through history.
        self.history_cursor: str | None = None
        self.empty_streak = 0
        self.history_done = False
        # Meter reading dates seen so far: each one starts a billing period.
        self.reading_dates: set[str] = set()

    # Persistence

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "days": self.days,
            "final": sorted(self.final),
            "history_cursor": self.history_cursor,
            "empty_streak": self.empty_streak,
            "history_done": self.history_done,
            "reading_dates": sorted(self.reading_dates),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageCache:
        """Restore from storage."""
        cache = cls()
        cache.days = data.get("days", {})
        cache.final = set(data.get("final", []))
        cache.history_cursor = data.get("history_cursor")
        cache.empty_streak = data.get("empty_streak", 0)
        cache.history_done = data.get("history_done", False)
        cache.reading_dates = set(data.get("reading_dates", []))
        return cache

    @classmethod
    def from_legacy_daily(cls, daily: dict[str, Any], history_done: bool) -> UsageCache:
        """Seed from the daily totals 1.0.x kept in the usage sensor attributes.

        Each day becomes one lump at 23:00 so the running sums (and therefore
        the Energy dashboard) stay continuous; the days are not final, so they
        get re-fetched with hourly detail.
        """
        cache = cls()
        for key, day in sorted(daily.items()):
            try:
                start = datetime.combine(date.fromisoformat(key), time(23), TIMEZONE)
            except ValueError:
                continue
            paid = _number(day.get("kwh"))
            free = _number(day.get("free_kwh"))
            cost = _number(day.get("dollars"))
            if paid or free or cost:
                cache.days[key] = [[start.isoformat(), paid + free, cost, free]]
        if cache.days:
            cache.history_cursor = min(cache.days)
        cache.history_done = history_done
        return cache

    # Fetching

    def plan(self, today: date, budget: int, fetch_history: bool) -> list[date]:
        """Return the days to fetch next, most useful first."""
        plan: list[date] = []
        recent_limit = today - timedelta(days=RECENT_DAYS)

        # 1. Recent days until their data is complete.
        for offset in range(1, RECENT_DAYS + 1):
            day = today - timedelta(days=offset)
            if day.isoformat() not in self.final:
                plan.append(day)

        # 2. Older days we hold without hourly detail (migrated from 1.0.x).
        plan.extend(
            sorted(
                (
                    date.fromisoformat(key)
                    for key in self.days
                    if key not in self.final and date.fromisoformat(key) < recent_limit
                ),
                reverse=True,
            )
        )

        # 3. Walk back through history.
        if not self.history_complete(today, fetch_history):
            cursor = (
                date.fromisoformat(self.history_cursor)
                if self.history_cursor
                else recent_limit
            )
            floor = (
                None if fetch_history else today - timedelta(days=SHORT_HISTORY_DAYS)
            )
            day = cursor - timedelta(days=1)
            while len(plan) < budget and (floor is None or day >= floor):
                plan.append(day)
                day -= timedelta(days=1)

        return plan[:budget]

    def history_complete(self, today: date, fetch_history: bool) -> bool:
        """Return True when there is no older history left to fetch."""
        if self.history_done:
            return True
        if fetch_history or not self.history_cursor:
            return False
        floor = today - timedelta(days=SHORT_HISTORY_DAYS)
        return date.fromisoformat(self.history_cursor) <= floor

    def store_day(self, day: date, hours: list[Hour], today: date) -> bool:
        """Store a fetched day; return True when the cached data changed."""
        key = day.isoformat()
        recent_limit = today - timedelta(days=RECENT_DAYS)

        if day < recent_limit and (
            self.history_cursor is None or key < self.history_cursor
        ):
            self.history_cursor = key
            if hours:
                self.empty_streak = 0
            else:
                self.empty_streak += 1
                if self.empty_streak >= END_OF_HISTORY_EMPTY_DAYS:
                    self.history_done = True

        # The API reports 24 hours on the day daylight saving ends, not 25.
        if len(hours) >= min(hours_in_day(day), 24) or day < today - timedelta(
            days=FINAL_AFTER_DAYS
        ):
            self.final.add(key)

        if not hours or self.days.get(key) == hours:
            return False
        self.days[key] = hours
        return True

    # Derived data

    @property
    def last_day(self) -> date | None:
        """Return the latest day with data."""
        return date.fromisoformat(max(self.days)) if self.days else None

    def totals_since(self, start: date | None, end: date | None = None) -> PeriodTotals:
        """Sum usage from ``start`` to ``end`` (inclusive; open-ended by default)."""
        paid = free = cost = 0.0
        last_day = None
        if start is not None:
            for key, hour in self._hours(start.isoformat()):
                if end is not None and key > end.isoformat():
                    break
                paid += hour[1] - hour[3]
                free += hour[3]
                cost += hour[2]
                last_day = key
        return PeriodTotals(
            start,
            paid,
            free,
            cost,
            date.fromisoformat(last_day) if last_day else None,
            end,
        )

    def add_reading_date(self, reading: date) -> bool:
        """Remember a meter reading date; return True when it is new."""
        if reading.isoformat() in self.reading_dates:
            return False
        self.reading_dates.add(reading.isoformat())
        return True

    def previous_period(self, current: date | None) -> PeriodTotals | None:
        """Totals of the billing period that ended the day before ``current``.

        Its start is the previous reading date seen; before two readings have
        been seen it is estimated as the same day one month earlier.
        """
        if current is None:
            return None
        earlier = [d for d in self.reading_dates if d < current.isoformat()]
        if earlier:
            start, estimated = date.fromisoformat(max(earlier)), False
        else:
            year, month = divmod(current.year * 12 + current.month - 2, 12)
            month += 1
            start, estimated = _same_day_in(year, month, current.day), True
        totals = self.totals_since(start, current - timedelta(days=1))
        totals.estimated_start = estimated
        return totals

    def statistics(self, first_day: str) -> StatisticsRows:
        """Return cumulative sums for every hour from ``first_day`` onwards."""
        rows = StatisticsRows([], [], [], [])
        paid = free = cost = 0.0
        for key, hour in self._hours(None):
            paid += hour[1] - hour[3]
            free += hour[3]
            cost += hour[2]
            if key >= first_day:
                rows.starts.append(datetime.fromisoformat(hour[0]))
                rows.paid_kwh.append(round(paid, 3))
                rows.cost.append(round(cost, 3))
                rows.free_kwh.append(round(free, 3))
        return rows

    def _hours(self, first_day: str | None) -> Iterator[tuple[str, Hour]]:
        for key in sorted(self.days):
            if first_day is None or key >= first_day:
                for hour in self.days[key]:
                    yield key, hour
