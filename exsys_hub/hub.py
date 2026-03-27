"""ExsysUsbHub — importable class for controlling Exsys Managed USB Hubs.

Quick start
-----------
>>> from exsys_hub import ExsysUsbHub
>>> with ExsysUsbHub("/dev/ttyUSB0") as hub:
...     print(hub.info())
...     hub.on(1)
...     hub.off(2)
...     print(hub.status())

With config file
----------------
>>> from exsys_hub import ExsysUsbHub, HubConfig
>>> cfg = HubConfig.load("exsys_hub.yaml")
>>> with ExsysUsbHub.from_config(cfg) as hub:
...     hub.on(1)
"""

from __future__ import annotations

from typing import Optional

import serial
from serial import SerialException

from .config import HubConfig

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
_BAUDRATE = 9600
_BYTESIZE = 8
_PARITY = "N"
_STOPBITS = 1
_TIMEOUT = 2


class HubError(Exception):
    """Raised when communication with the hub fails."""


class HubConnectionError(HubError):
    """Raised when the serial port cannot be opened."""


class HubTimeoutError(HubError):
    """Raised when the hub does not respond in time."""


class HubResponseError(HubError):
    """Raised when the hub returns an unexpected response."""


# ---------------------------------------------------------------------------
# ExsysUsbHub
# ---------------------------------------------------------------------------

class ExsysUsbHub:
    """Driver for Exsys Managed USB Hubs (4–16 ports, USB-Serial interface).

    Parameters
    ----------
    port:
        Serial port path, e.g. ``/dev/ttyUSB0``.
    baudrate:
        Baud rate (default 9600).
    timeout:
        Read timeout in seconds (default 2).

    Usage as context manager (recommended)
    ----------------------------------------
    >>> with ExsysUsbHub("/dev/ttyUSB0") as hub:
    ...     hub.on(1)

    Usage without context manager
    ------------------------------
    >>> hub = ExsysUsbHub("/dev/ttyUSB0")
    >>> hub.connect()
    >>> hub.on(1)
    >>> hub.close()
    """

    def __init__(
        self,
        port: str,
        baudrate: int = _BAUDRATE,
        timeout: int = _TIMEOUT,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._n_ports: Optional[int] = None
        self._model: Optional[str] = None
        self._fw: Optional[str] = None

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: HubConfig) -> "ExsysUsbHub":
        """Create an instance from a HubConfig object."""
        return cls(config.serial_port, config.baudrate, config.timeout)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ExsysUsbHub":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the serial connection and fetch device info.

        Raises
        ------
        HubConnectionError
            If the serial port cannot be opened.
        HubResponseError
            If the device does not identify as an Exsys hub.
        """
        try:
            self._ser = serial.Serial(
                self._port,
                baudrate=self._baudrate,
                bytesize=_BYTESIZE,
                parity=_PARITY,
                stopbits=_STOPBITS,
                timeout=self._timeout,
            )
        except SerialException as exc:
            raise HubConnectionError(
                f"Cannot open serial port {self._port!r}: {exc}"
            ) from exc

        # Fetch and cache device metadata
        self._fetch_info()

    def close(self) -> None:
        """Close the serial connection."""
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Return device metadata.

        Returns
        -------
        dict with keys ``model``, ``ports``, ``firmware``.

        Example
        -------
        >>> hub.info()
        {'model': 'EX-1504HMS', 'ports': 4, 'firmware': 'v1.0'}
        """
        self._ensure_connected()
        return {
            "model": self._model,
            "ports": self._n_ports,
            "firmware": self._fw,
        }

    def status(self) -> list[bool]:
        """Return current state of all ports (1-indexed: result[0] = port 1).

        Returns
        -------
        list of bool, length == number of ports.
        ``True`` means ON, ``False`` means OFF.
        """
        self._ensure_connected()
        return self._get_hub_state()

    def get_port(self, port: int) -> bool:
        """Return the current state of a single port (1-indexed).

        Parameters
        ----------
        port:
            Port number, 1-indexed.

        Returns
        -------
        ``True`` if ON, ``False`` if OFF.
        """
        self._ensure_connected()
        self._validate_port(port)
        return self._get_hub_state()[port - 1]

    def on(self, port: int) -> bool:
        """Turn a port ON.

        Parameters
        ----------
        port:
            Port number, 1-indexed.

        Returns
        -------
        ``True`` on success.
        """
        self._ensure_connected()
        self._validate_port(port)
        self._set_port_state(port - 1, True)
        return True

    def off(self, port: int) -> bool:
        """Turn a port OFF.

        Parameters
        ----------
        port:
            Port number, 1-indexed.

        Returns
        -------
        ``True`` on success.
        """
        self._ensure_connected()
        self._validate_port(port)
        self._set_port_state(port - 1, False)
        return True

    def reset(self) -> None:
        """Reset the hub."""
        self._ensure_connected()
        self._write_read(b"RHpass    \r")

    def factory_reset(self) -> list[bool]:
        """Restore factory defaults.

        Returns
        -------
        Port states after reset.
        """
        self._ensure_connected()
        response = self._write_read(b"RDpass    \r")
        if not response or response[0] != "G":
            raise HubResponseError(f"Hub rejected factory-reset: {response!r}")
        return self._get_hub_state()

    def save(self) -> None:
        """Save current port states as power-on defaults."""
        self._ensure_connected()
        response = self._write_read(b"WPpass    \r")
        if not response or response[0] != "G":
            raise HubResponseError(f"Hub rejected save command: {response!r}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise HubConnectionError(
                "Not connected. Call connect() or use as a context manager."
            )

    def _validate_port(self, port: int) -> None:
        if self._n_ports is None:
            return
        if not (1 <= port <= self._n_ports):
            raise ValueError(
                f"Port {port} out of range. This hub has {self._n_ports} ports (1–{self._n_ports})."
            )

    def _write_read(self, cmd: bytes) -> str:
        """Send cmd, return stripped UTF-8 response."""
        try:
            self._ser.write(cmd)
            raw = self._ser.readline()
        except SerialException as exc:
            raise HubError(f"Serial communication failed: {exc}") from exc
        if not raw:
            raise HubTimeoutError("No response from device (timeout).")
        return raw.decode("utf-8").strip()

    def _fetch_info(self) -> None:
        """Query device info and cache model/port count/firmware."""
        response = self._write_read(b"?Q\r")
        if "v" not in response:
            raise HubResponseError(
                f"Unexpected response to ?Q (not an Exsys hub?): {response!r}"
            )
        self._model = response.split("v")[0]
        self._n_ports = int(self._model[-2:])
        self._fw = "v" + response.split("v")[1]

    def _get_hub_state(self) -> list[bool]:
        response = self._write_read(b"GP\r")
        states = _parse_hub_ports(response, self._n_ports)
        if states is None:
            raise HubResponseError(f"Unexpected response to GP: {response!r}")
        return states

    def _set_port_state(self, port_idx: int, state: bool) -> None:
        """Set a port by 0-based index."""
        current = self._get_hub_state()
        current[port_idx] = state
        cmd = _message_from_hub_ports(current, self._n_ports)
        if cmd is None:
            raise HubError("Failed to build set-port command.")
        response = self._write_read(cmd)
        if not response or response[0] != "G":
            raise HubResponseError(f"Hub rejected set-port command: {response!r}")

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        connected = "connected" if self.is_connected else "disconnected"
        model = self._model or "?"
        return f"ExsysUsbHub({self._port!r}, model={model!r}, {connected})"


# ---------------------------------------------------------------------------
# Protocol helpers (pure functions, no I/O)
# ---------------------------------------------------------------------------

def _parse_hub_ports(message: str, n_ports: int) -> Optional[list[bool]]:
    """Decode 8-char hex response into port-state list."""
    if len(message) != 8:
        return None
    message = "".join(sum(zip(message[1::2], message[::2], strict=True), ()))
    message = message[::-1]
    message = int(message, 16)
    message = format(message, "b")[::-1]
    return [bool(int(c)) for c in message[:n_ports]]


def _message_from_hub_ports(ports: list[bool], n_ports: int) -> Optional[bytes]:
    """Encode port-state list into SPpass... command bytes."""
    if len(ports) != n_ports:
        return None
    message = "".join([str(int(c)) for c in ports][::-1])
    message = int(message, 2)
    message = (message | 0xFFFFFFFF << n_ports) & 0xFFFFFFFF
    message = str(hex(message))[2:].upper()
    message = "".join(sum(zip(message[1::2], message[::2], strict=True), ()))
    message = message[::-1]
    return b"SPpass    " + message.encode() + b"\r"
