"""Contact Energy Account Sensor."""
import logging
from datetime import datetime, timedelta
from homeassistant.helpers.entity import generate_entity_id
from custom_components.contact_energy.api import InvalidAuth
from homeassistant.util import slugify
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
from custom_components.contact_energy.const import (
    DOMAIN,
    DOMAIN_NAME
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(hours=8)
FORCED_SCAN_INTERVAL = timedelta(hours=24)
ENTITY_ID_FORMAT = DOMAIN + ".{}"

class ContactEnergyAccountSensor(SensorEntity):
    """Contact Energy Account Information Sensor."""

    def __init__(
        self, 
        hass,
        name, 
        api,
        icp,
        unit, 
        icon, 
        value_fn, 
        state_class=None,
        device_class=None
    ):
        """Initialize the sensor."""
        
        self.entity_id = generate_entity_id("sensor.{}", f"{DOMAIN}_{slugify(name)}", hass=hass)
        self._unique_id = f"{DOMAIN}_{icp}_{slugify(name)}"
        self._name = name
        
        self._api = api
        self._icp = icp
        self._state = None
        self._unit_of_measurement = unit
        self._icon = icon
        self._value_fn = value_fn
        self._state_class = state_class
        self._device_class = device_class
        self._attributes = {}
        self._last_update = None
        self._update_interval = SCAN_INTERVAL
        self._force_update_interval = FORCED_SCAN_INTERVAL

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit_of_measurement

    @property
    def icon(self):
        return self._icon

    @property
    def device_class(self):
        return self._device_class

    @property
    def state_class(self):
        return self._state_class

    @property
    def extra_state_attributes(self):
        return self._attributes
    
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._icp)},
            "name": f"{DOMAIN_NAME} installation connection point (ICP) {self._icp}",
            "manufacturer": DOMAIN_NAME,
            "model": "Smart Meter",
        }

    async def async_update(self):
        """Update the sensor."""
        try:
            account_data = await self._api.async_get_accounts()
            if account_data and "accountDetail" in account_data:
                self._state = self._value_fn(account_data)
                self._last_update = datetime.now()
                self._attributes["last_updated"] = self._last_update.isoformat()
                
                # Add payment history for monetary sensors
                if self._device_class == SensorDeviceClass.MONETARY:
                    payments = account_data["accountDetail"].get("payments", [])
                    self._attributes["recent_payments"] = [
                        {
                            "amount": payment["amount"],
                            "date": payment["date"]
                        }
                        for payment in payments
                    ]

        except InvalidAuth:
            _LOGGER.warning("Authentication error updating %s, will retry on next update", self._name)
        except Exception as error:
            _LOGGER.error("Error updating account sensor %s: %s", self._name, error)