"""Sensors for Contact Energy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ContactEnergyConfigEntry
from .const import CURRENCY, TIMEZONE
from .coordinator import (
    AccountData,
    ContactEnergyAccountCoordinator,
    ContactEnergyUsageCoordinator,
    UsageData,
    first_device,
    first_register,
    parse_date,
    parse_number,
)
from .entity import ContactEnergyEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AccountSensorDescription(SensorEntityDescription):
    """A sensor fed by the account coordinator."""

    device: str = "account"
    value_fn: Callable[[AccountData], Any]
    attrs_fn: Callable[[AccountData], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class UsageSensorDescription(SensorEntityDescription):
    """A sensor fed by the usage coordinator."""

    device: str = "electricity"
    value_fn: Callable[[UsageData], Any]
    billing_period: bool = True


def _detail(*keys: str) -> Callable[[AccountData], Any]:
    def value(data: AccountData) -> Any:
        node: Any = data.detail
        for key in keys:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    return value


def _recent_payments(data: AccountData) -> dict[str, Any]:
    return {
        "recent_payments": [
            {"amount": payment.get("amount"), "date": payment.get("date")}
            for payment in data.detail.get("payments", [])
        ]
    }


ACCOUNT_SENSORS: tuple[AccountSensorDescription, ...] = (
    AccountSensorDescription(
        key="account_balance",
        translation_key="account_balance",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY,
        value_fn=lambda d: parse_number(_detail("accountBalance", "currentBalance")(d)),
    ),
    AccountSensorDescription(
        key="next_bill_amount",
        translation_key="next_bill_amount",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY,
        value_fn=lambda d: parse_number(_detail("nextBill", "amount")(d)),
    ),
    AccountSensorDescription(
        key="next_bill_date",
        translation_key="next_bill_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: parse_date(_detail("nextBill", "date")(d)),
    ),
    AccountSensorDescription(
        key="payment_due",
        translation_key="payment_due",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY,
        value_fn=lambda d: parse_number(_detail("invoice", "amountDue")(d)),
        attrs_fn=_recent_payments,
    ),
    AccountSensorDescription(
        key="payment_due_date",
        translation_key="payment_due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: parse_date(_detail("invoice", "paymentDueDate")(d)),
    ),
    AccountSensorDescription(
        key="plan",
        translation_key="plan",
        value_fn=lambda d: d.plan,
    ),
    AccountSensorDescription(
        key="previous_reading_date",
        translation_key="previous_reading_date",
        device="electricity",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: d.reading_date,
    ),
    AccountSensorDescription(
        key="next_reading_date",
        translation_key="next_reading_date",
        device="electricity",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: parse_date(
            first_device(d.electricity).get("nextMeterReadDate")
        ),
    ),
    AccountSensorDescription(
        key="meter_reading",
        translation_key="meter_reading",
        device="electricity",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda d: parse_number(
            first_register(d.electricity).get("previousMeterReading")
        ),
    ),
)

GAS_SENSORS: tuple[AccountSensorDescription, ...] = (
    AccountSensorDescription(
        key="gas_meter_reading",
        translation_key="gas_meter_reading",
        device="gas",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=0,
        value_fn=lambda d: parse_number(
            first_register(d.gas).get("previousMeterReading")
        ),
    ),
    AccountSensorDescription(
        key="gas_meter_reading_date",
        translation_key="gas_meter_reading_date",
        device="gas",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: parse_date(
            first_register(d.gas).get("previousMeterReadingDate")
        ),
    ),
    AccountSensorDescription(
        key="gas_next_reading_date",
        translation_key="gas_next_reading_date",
        device="gas",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: parse_date(first_device(d.gas).get("nextMeterReadDate")),
    ),
)

USAGE_SENSORS: tuple[UsageSensorDescription, ...] = (
    UsageSensorDescription(
        key="usage",
        translation_key="usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: round(d.period.paid_kwh, 3),
    ),
    UsageSensorDescription(
        key="usage_free",
        translation_key="usage_free",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: round(d.period.free_kwh, 3),
    ),
    UsageSensorDescription(
        key="total_usage",
        translation_key="total_usage",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: round(d.period.total_kwh, 3),
    ),
    UsageSensorDescription(
        key="usage_cost",
        translation_key="usage_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        value_fn=lambda d: round(d.period.cost, 2),
    ),
    UsageSensorDescription(
        key="latest_day_usage",
        translation_key="latest_day_usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        billing_period=False,
        value_fn=lambda d: (
            round(d.latest_day.total_kwh, 3) if d.latest_day.last_day else None
        ),
    ),
    UsageSensorDescription(
        key="latest_day_cost",
        translation_key="latest_day_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY,
        suggested_display_precision=2,
        billing_period=False,
        value_fn=lambda d: (
            round(d.latest_day.cost, 2) if d.latest_day.last_day else None
        ),
    ),
    UsageSensorDescription(
        key="usage_data_date",
        translation_key="usage_data_date",
        device_class=SensorDeviceClass.DATE,
        billing_period=False,
        value_fn=lambda d: d.period.last_day,
    ),
)

GAS_USAGE_SENSORS: tuple[UsageSensorDescription, ...] = (
    UsageSensorDescription(
        key="gas_usage_last_month",
        translation_key="gas_usage_last_month",
        device="gas",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
        billing_period=False,
        value_fn=lambda d: d.gas_last_month,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ContactEnergyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    account = entry.runtime_data.account
    usage = entry.runtime_data.usage
    has_gas = account.data.gas is not None

    entities: list[SensorEntity] = [
        AccountSensor(account, description)
        for description in ACCOUNT_SENSORS + (GAS_SENSORS if has_gas else ())
    ]
    entities.extend(
        UsageSensor(usage, account.data, description)
        for description in USAGE_SENSORS + (GAS_USAGE_SENSORS if has_gas else ())
    )
    async_add_entities(entities)


class AccountSensor(ContactEnergyEntity[ContactEnergyAccountCoordinator], SensorEntity):
    """Account, bill and meter details."""

    entity_description: AccountSensorDescription

    def __init__(
        self,
        coordinator: ContactEnergyAccountCoordinator,
        description: AccountSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, coordinator.data, description.device, description.key
        )
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


class UsageSensor(ContactEnergyEntity[ContactEnergyUsageCoordinator], SensorEntity):
    """Usage totals for the current billing period."""

    entity_description: UsageSensorDescription

    def __init__(
        self,
        coordinator: ContactEnergyUsageCoordinator,
        account: AccountData,
        description: UsageSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, account, description.device, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Usage is only known once the first fetch has finished."""
        return super().available and self.coordinator.data is not None

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        """Return the start of the billing period."""
        if not self.entity_description.billing_period or self.coordinator.data is None:
            return None
        start = self.coordinator.data.period.start
        return datetime.combine(start, time(), TIMEZONE) if start else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the period the value covers."""
        if (data := self.coordinator.data) is None:
            return None
        if self.entity_description.key == "gas_usage_last_month":
            month: date | None = data.gas_last_month_start
            return {"month": month.strftime("%Y-%m") if month else None}
        if self.entity_description.key.startswith("latest_day"):
            return {
                "date": data.latest_day.last_day,
                "paid_kwh": round(data.latest_day.paid_kwh, 3),
                "free_kwh": round(data.latest_day.free_kwh, 3),
            }
        if not self.entity_description.billing_period:
            return None
        return {
            "period_start": data.period.start,
            "data_until": data.period.last_day,
        }
