"""Contact Energy sensors."""
import logging
from datetime import datetime, timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from custom_components.contact_energy.sensors import (
    ContactEnergyAccountSensor,
    ContactEnergyUsageSensor
)
from custom_components.contact_energy.api import ContactEnergyApi

from homeassistant.const import (
    CURRENCY_DOLLAR,
    CONF_EMAIL,
    CONF_PASSWORD,
    UnitOfEnergy
)

from custom_components.contact_energy.const import (
    CONF_USAGE_DAYS, 
    CONF_ACCOUNT_ID, 
    CONF_CONTRACT_ID, 
    CONF_CONTRACT_ICP,
    SENSOR_USAGE_NAME,
    SENSOR_ACCOUNT_BALANCE_NAME,
    SENSOR_NEXT_BILL_AMOUNT_NAME,
    SENSOR_NEXT_BILL_DATE_NAME,
    SENSOR_PAYMENT_DUE_NAME,
    SENSOR_PAYMENT_DUE_DATE_NAME,
    SENSOR_PREVIOUS_READING_DATE_NAME,
    SENSOR_NEXT_READING_DATE_NAME
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(hours=8)


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
        ContactEnergyUsageSensor(
            hass, 
            SENSOR_USAGE_NAME, 
            api, 
            icp, 
            UnitOfEnergy.KILO_WATT_HOUR,
            "mdi:meter-electric",
            SensorStateClass.TOTAL,
            SensorDeviceClass.ENERGY,
            usage_days
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_ACCOUNT_BALANCE_NAME,
            api,
            icp,
            CURRENCY_DOLLAR,
            "mdi:cash",
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.MONETARY,
            lambda data: data["accountDetail"]["accountBalance"]["currentBalance"],
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_NEXT_BILL_AMOUNT_NAME,
            api,
            icp,
            CURRENCY_DOLLAR,
            "mdi:cash-clock",
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.MONETARY,
            lambda data: data["accountDetail"]["nextBill"]["amount"],
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_NEXT_BILL_DATE_NAME,
            api,
            icp,
            None,
            "mdi:calendar",
            None,
            SensorDeviceClass.DATE,
            lambda data: datetime.strptime(
                data["accountDetail"]["nextBill"]["date"],
                "%d %b %Y"
            ).date().isoformat(),
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_PAYMENT_DUE_NAME,
            api,
            icp,
            CURRENCY_DOLLAR,
            "mdi:cash-marker",
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.MONETARY,
            lambda data: data["accountDetail"]["invoice"]["amountDue"],
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_PAYMENT_DUE_DATE_NAME,
            api,
            icp,
            None,
            "mdi:calendar-clock",
            None,
            SensorDeviceClass.DATE,
            lambda data: datetime.strptime(
                data["accountDetail"]["invoice"]["paymentDueDate"],
                "%d %b %Y"
            ).date().isoformat(),
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_PREVIOUS_READING_DATE_NAME,
            api,
            icp,
            None,
            "mdi:calendar",
            None,
            SensorDeviceClass.DATE,
            lambda data: datetime.strptime(
                data["accountDetail"]["contracts"][0]["devices"][0]["registers"][0]["previousMeterReadingDate"],
                "%d %b %Y"
            ).date().isoformat(),
        ),
        ContactEnergyAccountSensor(
            hass,
            SENSOR_NEXT_READING_DATE_NAME,
            api,
            icp,
            None,
            "mdi:calendar",
            None,
            SensorDeviceClass.DATE,
            lambda data: datetime.strptime(
                data["accountDetail"]["contracts"][0]["devices"][0]["nextMeterReadDate"],
                "%d %b %Y"
            ).date().isoformat(),
        ),
    ]
    async_add_entities(sensors, True)
    return True