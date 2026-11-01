"""Constants for the Contact Energy integration."""

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "contact_energy"
NAME = "Contact Energy"

# Contact Energy only supplies New Zealand: every date the API returns is local.
TIMEZONE = ZoneInfo("Pacific/Auckland")

CONF_ACCOUNT_ID = "account_id"
CONF_CONTRACT_ID = "contract_id"
CONF_CONTRACT_ICP = "contract_icp"
CONF_FETCH_HISTORY = "fetch_history"
# Entries created before 1.1.0 keep the original (un-suffixed) statistic ids so
# existing Energy dashboard configurations keep working.
CONF_LEGACY_STATISTIC_IDS = "legacy_statistic_ids"
# Options: the API has no gas prices, so the gas cost statistic is computed
# from rates the user enters. CONF_GAS_RATES keeps every rate with the month
# it applies from, so a price change does not rewrite earlier months.
CONF_GAS_PRICE = "gas_price"
CONF_GAS_DAILY_CHARGE = "gas_daily_charge"
CONF_GAS_RATES = "gas_rates"
# Contact Energy's costs (and the bill's line items) exclude GST; this option
# adds it to every cost the integration reports.
CONF_INCLUDE_GST = "include_gst"
GST_RATE = 0.15

CONTRACT_TYPE_ELECTRICITY = 1
# Natural gas and LPG Reticulated (piped LPG, meter in m³, no usage data).
CONTRACT_TYPE_NATURAL_GAS = 2
CONTRACT_TYPES_GAS = (CONTRACT_TYPE_NATURAL_GAS, 3)

ACCOUNT_UPDATE_INTERVAL = timedelta(hours=1)
USAGE_UPDATE_INTERVAL = timedelta(hours=1)
GAS_UPDATE_INTERVAL = timedelta(hours=12)
# Monthly gas usage is fetched a year at a time, at most this far back.
GAS_HISTORY_YEARS = 5

# Hourly usage can only be requested one day at a time and each request takes
# a few seconds, so history is fetched in batches.
REQUESTS_PER_UPDATE = 48
REQUEST_DELAY = 0.2
# Usage lands 1-3 days late: keep re-fetching recent days until they are complete.
RECENT_DAYS = 4
# A day older than this is not re-fetched again, even when hours are missing.
FINAL_AFTER_DAYS = 7
# This many empty days in a row while going back in time means the start of
# the account's history has been reached.
END_OF_HISTORY_EMPTY_DAYS = 5
# History kept when "fetch all history" is off (covers a billing period).
SHORT_HISTORY_DAYS = 35

CURRENCY = "NZD"
