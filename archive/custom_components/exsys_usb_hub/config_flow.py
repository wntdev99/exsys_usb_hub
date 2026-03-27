"""Config flow for Nilan integration."""

from __future__ import annotations

import logging
from typing import Any, Optional

import serial
from serial import SerialException
import serial.tools.list_ports
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.selector import selector

from .const import DOMAIN

STEP_SERIAL_DATA_SCHEMA = {
    vol.Required("name", default="Exsys USB Hub"): str,
}


_LOGGER = logging.getLogger(__name__)


async def async_validate_device(port: str) -> None:
    """Validate device."""
    ser = serial.Serial(
        port, baudrate=9600, bytesize=8, parity="N", stopbits=1, timeout=1
    )
    try:
        ser.write(b"?Q\r")
        response = ser.readline()
    except SerialException as value_error:
        ser.close()
        raise ValueError("cannot_connect") from value_error
    else:
        if b"v" not in response:
            ser.close()
            raise ValueError("invalid_response")
        ser.close()


class ExsysUsbHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Exsys USB Hub."""

    VERSION = 1

    data: Optional[dict(str, Any)]

    async def async_step_user(self, user_input: Optional[dict(str, Any)] = None):
        """Invoke when a user initiates a flow via the user interface."""
        return await self.async_step_serial(user_input)

    async def async_step_serial(self, user_input: Optional[dict(str, Any)] = None):
        """Configure Serial Entry."""
        errors: dict(str, str) = {}
        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        data_schema = STEP_SERIAL_DATA_SCHEMA

        if len(ports) == 0:
            raise ValueError("no_ports_found")
        port_opt = [str(port.device) for port in ports]
        data_schema[vol.Required("host_port")] = selector(
            {
                "select": {
                    "options": port_opt,
                }
            }
        )

        if user_input is not None:
            await self.async_set_unique_id(user_input["host_port"])
            self._abort_if_unique_id_configured()
            try:
                await async_validate_device(
                    user_input["host_port"],
                )
            except ValueError as error:
                errors["base"] = str(error)
            if not errors:
                # Input is valid, set data.
                self.data = user_input
                return self.async_create_entry(title=user_input["name"], data=self.data)
        return self.async_show_form(
            step_id="serial", data_schema=vol.Schema(data_schema), errors=errors
        )
