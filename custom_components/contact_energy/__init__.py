"""The Contact Energy integration."""
import logging
import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import ContactEnergyApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Contact Energy from a config entry."""
    _LOGGER.debug("Setting up Contact Energy integration for %s", entry.data["email"])
    
    hass.data.setdefault(DOMAIN, {})
    
    # Create API instance
    api = ContactEnergyApi(hass, entry.data["email"], entry.data["password"])
    
    try:
        if not await api.async_login():
            _LOGGER.error("Failed to log in during setup")
            return False
            
        _LOGGER.debug("Successfully logged in during setup")
        
        # Store API instance for platforms to use
        hass.data[DOMAIN][entry.entry_id] = api
        
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        return True
        
    except Exception as error:
        _LOGGER.exception("Error setting up Contact Energy integration: %s", error)
        return False

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        # Unload sensors
        if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            hass.data[DOMAIN].pop(entry.entry_id)
            
        return unload_ok
    
    except Exception as error:
        _LOGGER.exception("Error unloading Contact Energy integration: %s", error)
        return False

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)