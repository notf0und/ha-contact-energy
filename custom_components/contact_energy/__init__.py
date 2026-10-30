"""The Contact Energy integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ContactEnergyApi
from .const import CONF_LEGACY_STATISTIC_IDS
from .coordinator import ContactEnergyAccountCoordinator, ContactEnergyUsageCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]


@dataclass
class ContactEnergyRuntimeData:
    """Objects shared by the platforms of one config entry."""

    account: ContactEnergyAccountCoordinator
    usage: ContactEnergyUsageCoordinator


type ContactEnergyConfigEntry = ConfigEntry[ContactEnergyRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: ContactEnergyConfigEntry
) -> bool:
    """Set up Contact Energy from a config entry."""
    api = ContactEnergyApi(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    account = ContactEnergyAccountCoordinator(hass, entry, api)
    await account.async_config_entry_first_refresh()

    usage = ContactEnergyUsageCoordinator(hass, entry, api, account)
    await usage.async_load()

    entry.runtime_data = ContactEnergyRuntimeData(account, usage)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Fetching usage takes a while (one request per day); don't block startup.
    entry.async_create_background_task(
        hass, usage.async_refresh(), f"contact_energy usage {entry.entry_id}"
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ContactEnergyConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        # 1.0.x used fixed statistic ids; keep them so Energy dashboards keep working.
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_LEGACY_STATISTIC_IDS: True},
            minor_version=2,
        )
        _LOGGER.debug("Migrated config entry %s to version 1.2", entry.entry_id)
    return True
