"""Contact Energy Usage Sensor."""
from datetime import datetime, timedelta
import logging

from homeassistant.helpers.entity import generate_entity_id

from homeassistant.util import slugify
from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.const import (
    UnitOfEnergy,
)

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics

from custom_components.contact_energy.const import (
    DOMAIN,
    DOMAIN_NAME
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=8)
FORCED_SCAN_INTERVAL = timedelta(hours=24)
ENTITY_ID_FORMAT = DOMAIN + ".{}"

class ContactEnergyUsageSensor(SensorEntity):
    """Define Contact Energy Usage sensor."""

    def __init__(self, hass, name, api, icp, usage_days):
        """Initialize the sensor."""

        self.entity_id = generate_entity_id("sensor.{}", f"{DOMAIN}_{slugify(name)}", hass=hass)
        self._unique_id = f"{DOMAIN}_{icp}_{slugify(name)}"
        self._name = name
        
        self._icon = "mdi:meter-electric"
        self._state = 0
        self._unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._device_class = "energy"
        self._state_class = "total"
        self._state_attributes = {}
        self._usage_days = usage_days
        self._api = api
        self._icp = icp
        self._last_update = None
        self._update_failures = 0
        self._update_interval = SCAN_INTERVAL
        self._force_update_interval = FORCED_SCAN_INTERVAL

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Icon to use in the frontend."""
        return self._icon

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self._state_attributes

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def state_class(self):
        """Return the state class."""
        return self._state_class

    @property
    def device_class(self):
        """Return the device class."""
        return self._device_class

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._unique_id
    
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
        now = datetime.now()
        
        # Check if we need to force an update
        force_update = False
        if self._last_update:
            time_since_update = now - self._last_update
            if time_since_update > self._force_update_interval:
                _LOGGER.warning("More than 24 hours since last successful update, forcing update")
                force_update = True
                self._update_failures = 0  # Reset failure count on forced update

        try:
            _LOGGER.debug("Beginning usage update")

            # Check to see if our API Token is valid
            if not self._api._api_token:
                _LOGGER.info("Not logged in, attempting login...")
                if not await self._api.async_login():
                    _LOGGER.error("Failed to login - check credentials")
                    self._update_failures += 1
                    return False

            # Get today's date
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            _LOGGER.debug("Fetching usage data")

            kWhStatistics = []
            kWhRunningSum = 0
            dollarStatistics = []
            dollarRunningSum = 0

            freeKWhStatistics = []
            freeKWhRunningSum = 0

            currency = 'NZD'

            for i in range(self._usage_days):
                current_date = today - timedelta(days=self._usage_days - i)
                _LOGGER.debug("Fetching data for %s", current_date.strftime("%Y-%m-%d"))
                
                response = await self._api.get_usage(
                    str(current_date.year), 
                    str(current_date.month), 
                    str(current_date.day)
                )

                if not response or not response[0]:
                    _LOGGER.debug("No data available from %s onwards, stopping fetch", current_date.strftime("%Y-%m-%d"))
                    break

                for point in response:
                        if point['currency'] and currency != point['currency']:
                            currency = point['currency']
                        if point["value"]:
                            # If the off peak value is not '0.00' then the energy is free.
                            # HASSIO statistics requires us to add values as a sum of all previous values.
                            if point["offpeakValue"] == "0.00":
                                kWhRunningSum = kWhRunningSum + float(point["value"])
                                dollarRunningSum = dollarRunningSum + float(point["dollarValue"])
                            else:
                                freeKWhRunningSum = freeKWhRunningSum + float(
                                    point["value"]
                                )

                            freeKWhStatistics.append(
                                StatisticData(
                                    start=datetime.strptime(
                                        point["date"], "%Y-%m-%dT%H:%M:%S.%f%z"
                                    ),
                                    sum=freeKWhRunningSum,
                                )
                            )
                            kWhStatistics.append(
                                StatisticData(
                                    start=datetime.strptime(
                                        point["date"], "%Y-%m-%dT%H:%M:%S.%f%z"
                                    ),
                                    sum=kWhRunningSum,
                                )
                            )
                            dollarStatistics.append(
                                StatisticData(
                                    start=datetime.strptime(
                                        point["date"], "%Y-%m-%dT%H:%M:%S.%f%z"
                                    ),
                                    sum=dollarRunningSum,
                                )
                            )

            icp = self._icp
            kWhMetadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=f"Contact Energy - Electricity ({icp})",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:energy_consumption",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(self.hass, kWhMetadata, kWhStatistics)

            dollarMetadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=f"Contact Energy - Electricity Cost ({icp})",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:energy_consumption_in_dollars",
                unit_of_measurement=currency,
            )
            async_add_external_statistics(self.hass, dollarMetadata, dollarStatistics)

            freeKWHMetadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=f"Contact Energy - Free Electricity ({icp})",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:free_energy_consumption",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
            async_add_external_statistics(self.hass, freeKWHMetadata, freeKWhStatistics)

            self._state = kWhRunningSum
            self._last_update = now
            self._update_failures = 0
            return True

        except Exception as error:
            self._update_failures += 1
            _LOGGER.error("Error updating sensor (attempt %d): %s", self._update_failures, str(error))
            
            # If we've failed multiple times, try to re-login
            if self._update_failures >= 3:
                _LOGGER.warning("Multiple update failures, attempting to re-login")
                await self._api.async_login()
            
            # If this was a forced update that failed, schedule another update soon
            if force_update:
                _LOGGER.info("Scheduling another update attempt in 1 hour")
                self.async_schedule_update_ha_state(True)
            
            return False