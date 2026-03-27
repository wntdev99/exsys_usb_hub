"""Implements Exys Managed USB Hub devices."""

from __future__ import annotations

import asyncio
import logging

from serial import SerialException
import serial_asyncio_fast as serial_asyncio

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class Device:
    """Exsys Managed USB Hub."""

    def __init__(
        self,
        hass: HomeAssistant,
        name,
        host_port,
    ) -> None:
        """Create new entity of Device Class."""
        self.hass = hass
        self._device_name = name
        self._device_type = ""
        self._device_sw_ver = ""
        self._host_port = host_port
        self._hub_number_of_ports = None
        self._hub_port_array: list[bool] = [None]
        self._serial = None
        self._task = None

    async def async_setup(self) -> bool:
        """Setups Exsys Managed USB Hub."""
        _LOGGER.debug("Setup has started")
        if not await self._async_get_hub_info():
            return False
        _LOGGER.debug("Device Type = %s", str(self._device_type))
        if await self.async_get_hub_state() is None:
            return False
        return True

    async def _async_serial_handler(
        self, device, baudrate, bytesize, parity, stopbits, write_buf
    ) -> bytes:
        """Open connection, write and then read the data from the port."""
        logged_error = False
        try:
            reader, writer = await serial_asyncio.open_serial_connection(
                url=device,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            )
        except SerialException:
            if not logged_error:
                _LOGGER.exception("Unable to connect to the serial device %s", device)
                logged_error = True
        else:
            _LOGGER.debug(
                "Serial device %s connected and trying to send %s",
                device,
                str(write_buf),
            )
            try:
                writer.write(write_buf)
                await writer.drain()
            except SerialException:
                _LOGGER.exception("Error while writing serial device %s", device)
            else:
                try:
                    read_buf = await reader.readline()
                    _LOGGER.debug(
                        "Serial device %s sent %s",
                        device,
                        str(read_buf),
                    )
                except SerialException:
                    _LOGGER.exception("Error while reading serial device %s", device)
                else:
                    return read_buf

    @property
    def get_device_name(self):
        """Device name."""
        return self._device_name

    @property
    def get_device_type(self):
        """Device type."""
        return self._device_type

    @property
    def get_device_sw_version(self):
        """Device software version."""
        return self._device_sw_ver

    def get_hub_port_array(self):
        """Device Port States."""
        return self._hub_port_array

    def get_number_of_ports(self):
        """Device usb port quantity."""
        return self._hub_number_of_ports

    async def _async_serial_write_read(self, write_msg: bytes) -> str:
        """Write message and return read."""
        if self._task is not None:
            while not self._task.done():
                await asyncio.sleep(0.01)
        self._task = self.hass.loop.create_task(
            self._async_serial_handler(self._host_port, 9600, 8, "N", 1, write_msg)
        )
        response = await asyncio.gather(self._task)
        return response[0].decode("utf-8").strip()

    async def _async_get_hub_info(self) -> bool:
        """Get hardware type, model and software version. Returns True if successful."""
        response = await self._async_serial_write_read(b"?Q\r")
        if "v" in response:
            self._device_type = response.split("v")[0]
            self._hub_number_of_ports = int(self._device_type[-2:])
            self._device_sw_ver = "v" + str(response.split("v")[1])
            return True
        _LOGGER.error("Could not read _get_hub_info")
        return False

    def _message_from_hub_ports(self, ports: list[bool]) -> bytes | None:
        """Generate hub ports bytes from bool array."""
        if len(ports) == self._hub_number_of_ports:
            message = "".join([str(int(c)) for c in ports][::-1])
            message = int(message, 2)
            message = (message | 0xFFFFFFFF << self._hub_number_of_ports) & 0xFFFFFFFF
            message = str(hex(message))[2:].upper()
            message = "".join(sum(zip(message[1::2], message[::2], strict=True), ()))
            message = message[::-1]
            return b"SPpass    " + message.encode() + b"\r"
        return None

    def _parse_hub_ports(self, message: str) -> list[bool] | None:
        """Parse hub ports from input message and return list in port order."""
        if (len(message) == 8) and (self._hub_number_of_ports is not None):
            message = "".join(sum(zip(message[1::2], message[::2], strict=True), ()))
            message = message[::-1]
            message = int(message, 16)
            message = format(message, "b")[::-1]
            message = list(message[: self._hub_number_of_ports])
            return [bool(int(c)) for c in message]
        return None

    async def async_get_hub_state(self) -> list[bool] | None:
        """Get Hub Port State."""
        response = await self._async_serial_write_read(b"GP\r")
        self._hub_port_array = self._parse_hub_ports(response)
        if self._hub_port_array is not None:
            return self._hub_port_array
        _LOGGER.error("Could not read get_hub_state")
        return None

    async def async_set_port_state(self, port: int, state: bool) -> bool:
        """Set port state."""
        port_array = self._hub_port_array
        if port_array is not None:
            port_array[port] = state
            message = self._message_from_hub_ports(port_array)
            response = await self._async_serial_write_read(message)
            if response is not None:
                if response[0] == "G":
                    self._hub_port_array = port_array
                    return True
        _LOGGER.error("Could not set set_port_state")
        return False

    async def async_reset_hub(self) -> bool:
        """Reset Hub."""
        await self._async_serial_write_read(b"RHpass    \r")
        return True

    async def async_restore_factory_defaults(self) -> bool:
        """Restore hub factory defaults."""
        response = await self._async_serial_write_read(b"RDpass    \r")
        if response[0] == "G":
            await self.async_get_hub_state()
            return True
        _LOGGER.error("Could not restore_factory_defaults")
        return False

    async def async_save_port_states(self) -> bool:
        """Save hub port states as start-up states."""
        response = await self._async_serial_write_read(b"WPpass    \r")
        if response[0] == "G":
            return True
        _LOGGER.error("Could not save_port_states")
        return False
