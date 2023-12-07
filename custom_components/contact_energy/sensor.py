"""Contact Energy sensors."""
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfEnergy,
    CURRENCY_DOLLAR,
    CONF_EMAIL,
    CONF_PASSWORD,
)

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics

from .api import ContactEnergyApi
from .const import DOMAIN, SENSOR_USAGE_NAME, CONF_USAGE_DAYS, CONF_ACCOUNT_ID, CONF_CONTRACT_ID, CONF_CONTRACT_ICP

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=6)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Contact Energy sensors from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    account_id = entry.data[CONF_ACCOUNT_ID]
    contract_id = entry.data[CONF_CONTRACT_ID]
    usage_days = entry.data.get(CONF_USAGE_DAYS, 10)
    icp = entry.data[CONF_CONTRACT_ICP]

    api = ContactEnergyApi(hass, email, password, account_id, contract_id)
    
    # Initialize API connection
    if not await api.async_login():
        _LOGGER.error("Failed to connect to Contact Energy API")
        return False

    sensors = [
        ContactEnergyUsageSensor(SENSOR_USAGE_NAME, api, usage_days, icp),
        ContactEnergyAccountSensor(
            "Account Balance",
            "account_balance",
            api,
            CURRENCY_DOLLAR,
            "mdi:cash",
            lambda data: data["accountDetail"]["accountBalance"]["currentBalance"],
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.MONETARY,
        ),
        ContactEnergyAccountSensor(
            "Next Bill Amount",
            "next_bill_amount",
            api,
            CURRENCY_DOLLAR,
            "mdi:cash-clock",
            lambda data: data["accountDetail"]["nextBill"]["amount"],
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.MONETARY,
        ),
        ContactEnergyAccountSensor(
            "Next Bill Date",
            "next_bill_date",
            api,
            None,
            "mdi:calendar",
            lambda data: datetime.strptime(
                data["accountDetail"]["nextBill"]["date"],
                "%d %b %Y"
            ).date().isoformat(),
            None,
            SensorDeviceClass.DATE,
        ),
        ContactEnergyAccountSensor(
            "Payment Due",
            "payment_due",
            api,
            CURRENCY_DOLLAR,
            "mdi:cash-marker",
            lambda data: data["accountDetail"]["invoice"]["amountDue"],
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.MONETARY,
        ),
        ContactEnergyAccountSensor(
            "Payment Due Date",
            "payment_due_date",
            api,
            None,
            "mdi:calendar-clock",
            lambda data: datetime.strptime(
                data["accountDetail"]["invoice"]["paymentDueDate"],
                "%d %b %Y"
            ).date().isoformat(),
            None,
            SensorDeviceClass.DATE,
        ),
        ContactEnergyAccountSensor(
            "Previous Reading Date",
            "previous_reading_date",
            api,
            None,
            "mdi:calendar",
            lambda data: datetime.strptime(
                data["accountDetail"]["contracts"][0]["devices"][0]["registers"][0]["previousMeterReadingDate"],
                "%d %b %Y"
            ).date().isoformat(),
            None,
            SensorDeviceClass.DATE,
        ),
        ContactEnergyAccountSensor(
            "Next Reading Date",
            "next_reading_date",
            api,
            None,
            "mdi:calendar",
            lambda data: datetime.strptime(
                data["accountDetail"]["contracts"][0]["devices"][0]["nextMeterReadDate"],
                "%d %b %Y"
            ).date().isoformat(),
            None,
            SensorDeviceClass.DATE,
        ),
    ]
    async_add_entities(sensors, True)
    return True

class ContactEnergyUsageSensor(SensorEntity):
    """Define Contact Energy Usage sensor."""

    def __init__(self, name, api, usage_days, icp):
        """Initialize the sensor."""
        self._name = name
        self._icon = "mdi:meter-electric"
        self._state = 0
        self._unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._unique_id = f"{DOMAIN}_{name}"
        self._device_class = "energy"
        self._state_class = "total"
        self._state_attributes = {}
        self._usage_days = usage_days
        self._api = api
        self._icp = icp
        self._last_update = None
        self._update_failures = 0
        self._force_update_interval = timedelta(days=1)

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
        

class ContactEnergyAccountSensor(SensorEntity):
    """Contact Energy Account Information Sensor."""

    def __init__(
        self, 
        name, 
        unique_id_suffix, 
        api, 
        unit, 
        icon, 
        value_fn, 
        state_class=None,
        device_class=None
    ):
        """Initialize the sensor."""
        self._name = name
        self._unique_id = f"{DOMAIN}_{unique_id_suffix}"
        self._api = api
        self._state = None
        self._unit_of_measurement = unit
        self._icon = icon
        self._value_fn = value_fn
        self._state_class = state_class
        self._device_class = device_class
        self._attributes = {}
        self._last_update = None

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

        except Exception as error:
            _LOGGER.error("Error updating account sensor %s: %s", self._name, error)