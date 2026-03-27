"""Platform for switch integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .__init__ import ExsysUsbHubEntity
from .const import DOMAIN


async def async_setup_entry(HomeAssistant, config_entry, async_add_entities):
    """Set up the switch platform."""
    device = HomeAssistant.data[DOMAIN][config_entry.entry_id]
    switches = []
    number_of_ports = device.get_number_of_ports()
    for i in range(number_of_ports):
        switches.extend(
            [
                ExsysUsbHubSwitch(
                    device,
                    i,
                )
            ]
        )
    async_add_entities(switches, update_before_add=True)


class ExsysUsbHubSwitch(SwitchEntity, ExsysUsbHubEntity):
    """Representation of a Switch."""

    def __init__(self, device, port_number) -> None:
        """Init Switch."""
        super().__init__(device)
        self._port_number = port_number
        self._device = device
        self._attr_has_entity_name = True
        self._attr_translation_key = "port"
        self._attr_translation_placeholders = {
            "port_number": str(self._port_number + 1)
        }
        self._attr_unique_id = f"port_{self._port_number + 1}"

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        await getattr(self._device, "async_set_port_state")(self._port_number, False)
        await self.async_update()

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        await getattr(self._device, "async_set_port_state")(self._port_number, True)
        await self.async_update()

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        port_array = self._device.get_hub_port_array()
        if port_array is not None:
            self._attr_is_on = port_array[self._port_number]
