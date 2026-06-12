"""HubConfig — YAML-based configuration management for ExsysUsbHub."""

from __future__ import annotations

import os
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise ImportError("pyyaml is required: pip install pyyaml") from exc

_DEFAULT: dict[str, Any] = {
    "device": {
        "port": "/dev/ttyUSB0",
        "baudrate": 9600,
        "timeout": 2,
    },
    "ports": {
        1: "",
        2: "",
        3: "",
        4: "",
    },
}

_COMMENT_HEADER = """\
# Exsys USB Hub configuration
#
# device:
#   port     - serial port path (e.g. /dev/ttyUSB0)
#   baudrate - baud rate (default: 9600)
#   timeout  - read timeout in seconds (default: 2)
#
# ports:
#   Assign a label to each port for display purposes.
#   Leave empty ("") to use the default "Port N" label.
#
"""


class HubConfig:
    """Load, modify, and persist hub configuration from a YAML file.

    Example
    -------
    >>> cfg = HubConfig.load("exsys_hub.yaml")
    >>> cfg.serial_port
    '/dev/ttyUSB0'
    >>> cfg.port_name(1)
    'Z-Wave Dongle'
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "HubConfig":
        """Return a HubConfig with factory defaults."""
        import copy
        return cls(copy.deepcopy(_DEFAULT))

    @classmethod
    def load(cls, path: str) -> "HubConfig":
        """Load config from a YAML file. Raises FileNotFoundError if missing."""
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Config file not found: {path!r}\n"
                "Run `python exsys_cli.py config init` to create one."
            )
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Ensure required keys exist (merge with defaults)
        merged = _deep_merge(_DEFAULT, data)
        return cls(merged)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Write current config to path (creates parent directories if needed)."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_COMMENT_HEADER)
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)

    # ------------------------------------------------------------------
    # Device properties
    # ------------------------------------------------------------------

    @property
    def serial_port(self) -> str:
        return self._data["device"]["port"]

    @serial_port.setter
    def serial_port(self, value: str) -> None:
        self._data["device"]["port"] = value

    @property
    def baudrate(self) -> int:
        return int(self._data["device"].get("baudrate", 9600))

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        self._data["device"]["baudrate"] = int(value)

    @property
    def timeout(self) -> int:
        return int(self._data["device"].get("timeout", 2))

    @timeout.setter
    def timeout(self, value: int) -> None:
        self._data["device"]["timeout"] = int(value)

    # ------------------------------------------------------------------
    # Port name helpers
    # ------------------------------------------------------------------

    def port_name(self, port: int) -> str:
        """Return the label for port (1-indexed), or '' if not set."""
        return self._data.get("ports", {}).get(port) or ""

    def set_port_name(self, port: int, name: str) -> None:
        """Set label for port (1-indexed)."""
        if "ports" not in self._data:
            self._data["ports"] = {}
        self._data["ports"][port] = name

    def port_label(self, port: int) -> str:
        """Return 'Name (Port N)' if named, else 'Port N'."""
        name = self.port_name(port)
        return f"{name} (Port {port})" if name else f"Port {port}"

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return self._data

    def __repr__(self) -> str:
        return (
            f"HubConfig(port={self.serial_port!r}, "
            f"baudrate={self.baudrate}, timeout={self.timeout})"
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
