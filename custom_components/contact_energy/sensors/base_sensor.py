"""Contact Energy Account Sensor."""
from datetime import datetime, timedelta
from homeassistant.helpers.entity import generate_entity_id
from custom_components.contact_energy.api import InvalidAuth
from homeassistant.util import slugify
from homeassistant.components.sensor import SensorEntity
from custom_components.contact_energy.const import (
    DOMAIN,
    DOMAIN_NAME
)

SCAN_INTERVAL = timedelta(hours=8)
FORCED_SCAN_INTERVAL = timedelta(hours=24)
ENTITY_ID_FORMAT = DOMAIN + ".{}"

class BaseSensor(SensorEntity):
    """Contact Energy Base Sensor."""

    def __init__(
        self, 
        hass,
        name, 
        api,
        icp,
        unit, 
        icon, 
        state_class=None,
        device_class=None
    ):
        """Initialize the sensor."""
        self.entity_id = generate_entity_id("sensor.{}", f"{DOMAIN}_{slugify(name)}", hass=hass)
        self._unique_id = f"{DOMAIN}_{icp}_{slugify(name)}"
        self._name = name
        self._api = api
        self._icp = icp
        self._icon = icon
        self._unit_of_measurement = unit
        self._state_class = state_class
        self._device_class = device_class
        self._last_update = None
        self._attributes = {}
        self._update_failures = 0
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