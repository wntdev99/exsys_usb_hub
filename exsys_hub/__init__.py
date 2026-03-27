"""exsys_hub — Python module for controlling Exsys Managed USB Hubs.

Usage
-----
>>> from exsys_hub import ExsysUsbHub, HubConfig

>>> # Direct usage
>>> with ExsysUsbHub("/dev/ttyUSB0") as hub:
...     print(hub.info())
...     hub.on(1)
...     hub.off(2)
...     print(hub.status())

>>> # Config-based usage
>>> cfg = HubConfig.load("exsys_hub.yaml")
>>> with ExsysUsbHub.from_config(cfg) as hub:
...     hub.on(1)
"""

from .hub import ExsysUsbHub, HubError, HubConnectionError, HubTimeoutError, HubResponseError
from .config import HubConfig

__all__ = [
    "ExsysUsbHub",
    "HubConfig",
    "HubError",
    "HubConnectionError",
    "HubTimeoutError",
    "HubResponseError",
]
