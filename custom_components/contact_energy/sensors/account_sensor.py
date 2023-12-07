"""Contact Energy Account Sensor."""
import logging
from datetime import datetime
from typing import Callable, Optional, Dict, Any

from custom_components.contact_energy.sensors.base_sensor import BaseSensor
from custom_components.contact_energy.api import InvalidAuth
from homeassistant.components.sensor import SensorDeviceClass

_LOGGER = logging.getLogger(__name__)


class ContactEnergyAccountSensor(BaseSensor):
    """Sensor to track Contact Energy account details."""

    def __init__(
        self,
        hass,
        name: str,
        api,
        icp: str,
        unit: str,
        icon: str,
        state_class: Optional[str] = None,
        device_class: Optional[str] = None,
        value_fn: Callable[[Dict[str, Any]], Any] = lambda _: None,
    ):
        """Initialize the sensor."""
        super().__init__(hass, name, api, icp, unit, icon, state_class, device_class)
        self._value_fn = value_fn
        self._state = None

    async def async_update(self):
        """Fetch new data and update the sensor state."""
        try:
            account_data = await self._fetch_account_data()
            self._state = self._value_fn(account_data)
            self._update_attributes(account_data)
        except InvalidAuth:
            _LOGGER.warning("Authentication error updating %s, will retry on next update", self._name)
        except Exception as error:
            _LOGGER.error("Unexpected error updating account sensor %s: %s", self._name, error)

    async def _fetch_account_data(self) -> Dict[str, Any]:
        """Fetch account details from API."""
        return await self._api.async_get_accounts() or {}

    def _update_attributes(self, account_data: Dict[str, Any]):
        """Update sensor attributes."""
        self._last_update = datetime.now()
        self._attributes["last_updated"] = self._last_update.isoformat()

        if self._device_class == SensorDeviceClass.MONETARY:
            self._attributes["recent_payments"] = self._extract_recent_payments(account_data)

    @staticmethod
    def _extract_recent_payments(account_data: Dict[str, Any]) -> list:
        """Extract recent payment history."""
        return [
            {"amount": payment["amount"], "date": payment["date"]}
            for payment in account_data.get("accountDetail", {}).get("payments", [])
        ]
