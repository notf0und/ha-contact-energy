"""Button to fetch usage right away."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ContactEnergyConfigEntry
from .coordinator import ContactEnergyUsageCoordinator
from .entity import ContactEnergyEntity

PARALLEL_UPDATES = 1

BACKFILL = ButtonEntityDescription(
    key="backfill",
    translation_key="backfill",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ContactEnergyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    data = entry.runtime_data
    async_add_entities([BackfillButton(data.usage, data.account.data)])


class BackfillButton(ContactEnergyEntity[ContactEnergyUsageCoordinator], ButtonEntity):
    """Fetch the next batch of usage (recent days, then history) now."""

    entity_description = BACKFILL

    def __init__(self, coordinator: ContactEnergyUsageCoordinator, account) -> None:
        """Initialize the button."""
        super().__init__(coordinator, account, "electricity", BACKFILL.key)

    @property
    def available(self) -> bool:
        """The button works even when the last fetch failed."""
        return True

    async def async_press(self) -> None:
        """Fetch usage now."""
        await self.coordinator.async_backfill_now()
