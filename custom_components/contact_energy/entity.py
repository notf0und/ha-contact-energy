"""Base entity for Contact Energy."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import CONF_CONTRACT_ICP, DOMAIN, NAME
from .coordinator import AccountData, first_device

CONFIGURATION_URL = "https://contact.co.nz"


def _meter_model(contract: dict[str, Any] | None, default: str) -> str:
    meter_type = (contract or {}).get("meterType")
    return meter_type.title() if meter_type else default


def device_info(kind: str, account: AccountData, icp: str) -> DeviceInfo:
    """Build the device for "electricity", "gas" or "account" entities."""
    if kind == "account":
        account_id = str(account.detail.get("id"))
        return DeviceInfo(
            identifiers={(DOMAIN, f"account_{account_id}")},
            name=f"{NAME} Account",
            manufacturer=NAME,
            model=account.plan or "Account",
            serial_number=account_id,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=CONFIGURATION_URL,
        )
    if kind == "gas" and account.gas:
        return DeviceInfo(
            identifiers={(DOMAIN, account.gas["icp"])},
            name=f"{NAME} Gas",
            manufacturer=NAME,
            model=_meter_model(account.gas, "Gas Meter"),
            serial_number=first_device(account.gas).get("serialNumber"),
            configuration_url=CONFIGURATION_URL,
        )
    # The identifier is the ICP, as in 1.0.x, so the existing device is kept.
    return DeviceInfo(
        identifiers={(DOMAIN, icp)},
        name=f"{NAME} Electricity",
        manufacturer=NAME,
        model=_meter_model(account.electricity, "Electricity Meter"),
        serial_number=first_device(account.electricity).get("serialNumber"),
        configuration_url=CONFIGURATION_URL,
    )


class ContactEnergyEntity[CoordinatorT: DataUpdateCoordinator[Any]](
    CoordinatorEntity[CoordinatorT]
):
    """An entity attached to one of the integration's devices."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CoordinatorT, account: AccountData, kind: str, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        icp = coordinator.config_entry.data[CONF_CONTRACT_ICP]
        # Same unique id scheme as 1.0.x so entity ids and history are kept.
        self._attr_unique_id = f"{DOMAIN}_{icp}_{key}"
        self._attr_device_info = device_info(kind, account, icp)
