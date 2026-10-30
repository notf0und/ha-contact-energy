"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.contact_energy.const import DOMAIN, TIMEZONE

ACCOUNT_ID = "500000001"
ELEC_ID = "1300000001"
GAS_ID = "1300000002"
ICP = "0000123456AB1CD"
GAS_ICP = "0000654321XY2ZW"

ENTRY_DATA = {
    "email": "user@example.com",
    "password": "secret",
    "fetch_history": True,
    "account_id": ACCOUNT_ID,
    "contract_id": ELEC_ID,
    "contract_icp": ICP,
}


def contract(
    contract_id: str, icp: str, contract_type: int, unit: str
) -> dict[str, Any]:
    """A contract shaped like /accounts/v2 returns it."""
    return {
        "id": contract_id,
        "icp": icp,
        "meterType": "SMART METER" if contract_type == 1 else "STANDARD METER",
        "contractType": contract_type,
        "contractTypeLabel": "Electricity" if contract_type == 1 else "Natural Gas",
        "premise": {
            "id": "2000000001",
            "supplyAddress": {"shortForm": "1 Example Street, Auckland 1010"},
        },
        "devices": [
            {
                "id": "2000000009",
                "serialNumber": "12345678",
                "nextMeterReadDate": "27 Nov 2026",
                "registers": [
                    {
                        "id": "001",
                        "previousMeterReading": "8078.00",
                        "readingUnit": unit,
                        "previousMeterReadingDate": "25 Oct 2026",
                    }
                ],
            }
        ],
    }


def accounts(gas: bool = True) -> dict[str, Any]:
    """A /accounts/v2 response."""
    contracts = [contract(ELEC_ID, ICP, 1, "kWH")]
    if gas:
        contracts.insert(0, contract(GAS_ID, GAS_ICP, 2, "M3"))
    return {
        "accountsSummary": [{"id": ACCOUNT_ID, "contracts": []}],
        "accountDetail": {
            "id": ACCOUNT_ID,
            "accountBalance": {"currentBalance": 0},
            "invoice": {"amountDue": 342.93, "paymentDueDate": "15 Oct 2026"},
            "nextBill": {"date": "30 Nov 2026", "amount": 432.25},
            "payments": [{"amount": "$342.93", "date": "15 Oct 2026"}],
            "contracts": contracts,
        },
    }


PLANS = {
    "accountId": ACCOUNT_ID,
    "premises": [
        {
            "premiseId": "2000000001",
            "services": [
                {
                    "serviceType": "ELEC",
                    "contract": {"contractId": ELEC_ID},
                    "planDetails": {
                        "externalPlanDescription": "Good Nights (Monday - Friday)"
                    },
                }
            ],
        }
    ],
}


def hourly(day: date, free_from: int = 21) -> list[dict[str, Any]]:
    """Hourly points for one day: 0.5 kWh/h at $0.25, free from ``free_from``."""
    points = []
    start = datetime.combine(day, datetime.min.time(), TIMEZONE).astimezone(UTC)
    for hour in range(24):
        moment = (start + timedelta(hours=hour)).astimezone(TIMEZONE)
        if moment.date() != day:
            break
        free = moment.hour >= free_from
        points.append(
            {
                "date": moment.isoformat(timespec="milliseconds"),
                "value": "0.50",
                "dollarValue": "0.000" if free else "0.250",
                "offpeakValue": "0.50" if free else "0.00",
                "unchargedValue": "0.50" if free else "0.00",
                "offpeakDollarValue": "0.000",
                "unit": "kWh",
            }
        )
    return points


async def fake_usage(contract_id, account_id, interval, start, end):
    """Usage endpoint: hourly electricity for the last 60 days, monthly gas."""
    if interval == "monthly":
        return [
            {"date": "2026-08-01T00:00:00.000+12:00", "value": "546.753"},
            {"date": "2026-09-01T00:00:00.000+12:00", "value": "555.090"},
        ]
    if contract_id != ELEC_ID or interval != "hourly":
        return []
    today = datetime.now(TIMEZONE).date()
    if start >= today - timedelta(days=1) or start < today - timedelta(days=60):
        return []
    return hourly(start)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: None, enable_custom_integrations: None
) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def api() -> Generator[dict[str, AsyncMock]]:
    """Patch the API client."""
    base = "custom_components.contact_energy.api.ContactEnergyApi"
    with (
        patch(f"{base}.async_login", AsyncMock()) as login,
        patch(
            f"{base}.async_get_accounts", AsyncMock(side_effect=lambda *_: accounts())
        ) as get_accounts,
        patch(f"{base}.async_get_plan_details", AsyncMock(return_value=PLANS)) as plans,
        patch(f"{base}.async_get_usage", AsyncMock(side_effect=fake_usage)) as usage,
    ):
        yield {"login": login, "accounts": get_accounts, "plans": plans, "usage": usage}


@pytest.fixture
def entry() -> MockConfigEntry:
    """A config entry as created by 1.1.0."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=ELEC_ID,
        data=ENTRY_DATA,
        version=1,
        minor_version=2,
        title="Contact Energy - 1 Example Street",
    )
