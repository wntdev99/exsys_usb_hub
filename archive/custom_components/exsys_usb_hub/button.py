"""Platform for button integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .__init__ import ExsysUsbHubEntity
from .const import DOMAIN

ATTRIBUTE_TO_BUTTONS = [
    "async_reset_hub",
    "async_restore_factory_defaults",
    "async_save_port_states",
]


async def async_setup_entry(HomeAssistant, config_entry, async_add_entities):
    """Set up the button platform."""
    device = HomeAssistant.data[DOMAIN][config_entry.entry_id]
    buttons = []
    for attribute in ATTRIBUTE_TO_BUTTONS:
        buttons.extend([ExsysUsbHubButton(device, attribute)])
    async_add_entities(buttons, update_before_add=True)


class ExsysUsbHubButton(ButtonEntity, ExsysUsbHubEntity):
    """Representation of a Button."""

    def __init__(
        self,
        device,
        attribute,
    ) -> None:
        """Init Button."""
        super().__init__(device)
        self._device = device
        self._attribute = attribute
        self._attr_entity_category = EntityCategory.CONFIG
        self._name = attribute.split("async_")[1]
        self._attr_has_entity_name = True
        self._attr_translation_key = self._name
        self._attr_unique_id = self._name

    async def async_press(self) -> None:
        """Handle the button press."""
        await getattr(self._device, self._attribute)()
