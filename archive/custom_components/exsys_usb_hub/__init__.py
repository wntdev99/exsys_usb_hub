"""The Nilan integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .device import Device

PLATFORMS = [
    "button",
    "switch",
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Exsys USB Hub from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    for instance in hass.data[DOMAIN].values():
        if entry.data["host_port"] in instance["host_port"]:
            return False
    hass.data[DOMAIN][entry.entry_id] = entry.data
    name = entry.data["name"]
    host_port = entry.data["host_port"]

    device = Device(hass, name, host_port)
    try:
        if not await device.async_setup():
            return False
    except ValueError as ex:
        raise ConfigEntryNotReady(f"Timeout while connecting {host_port}") from ex

    hass.data[DOMAIN][entry.entry_id] = device

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class ExsysUsbHubEntity(Entity):
    """Exsys Usb Hub Entity."""

    def __init__(self, device: Device) -> None:
        """Initialize the instance."""
        self._device = device

    @property
    def device_info(self):
        """Device Info."""
        unique_id = self._device.get_device_name + self._device.get_device_type

        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, unique_id),
            },
            "name": self._device.get_device_name,
            "manufacturer": "Exsys",
            "model": self._device.get_device_type,
            "sw_version": self._device.get_device_sw_version,
        }
