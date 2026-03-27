# exsys_hub

Python module for controlling Exsys Managed USB Hubs over serial — no Home Assistant required.

Tested with **EX-1504HMS** (4–16 port hubs with USB-Serial management interface).

---

## Install

```bash
pip install pyserial pyyaml
```

Serial port permission (one-time):
```bash
sudo usermod -aG dialout $USER   # re-login required
```

---

## Quick Start

```python
from exsys_hub import ExsysUsbHub

with ExsysUsbHub("/dev/ttyUSB0") as hub:
    print(hub.info())     # {'model': 'CENTOS000104', 'ports': 4, 'firmware': 'v04'}
    print(hub.status())   # [True, True, True, True]

    hub.off(1)            # Port 1 OFF
    hub.on(1)             # Port 1 ON
    print(hub.get_port(1))  # True
```

---

## API Reference

### `ExsysUsbHub(port, baudrate=9600, timeout=2)`

| Method | Returns | Description |
|---|---|---|
| `info()` | `dict` | `model`, `ports`, `firmware` |
| `status()` | `list[bool]` | All port states (index 0 = Port 1) |
| `get_port(port)` | `bool` | Single port state (1-indexed) |
| `on(port)` | `bool` | Turn port ON |
| `off(port)` | `bool` | Turn port OFF |
| `reset()` | `None` | Reset the hub |
| `factory_reset()` | `list[bool]` | Restore factory defaults, returns new states |
| `save()` | `None` | Save current states as power-on defaults |
| `is_connected` | `bool` | Connection status |

### Context manager (recommended)

```python
with ExsysUsbHub("/dev/ttyUSB0") as hub:
    hub.on(2)
```

### Manual connect / close

```python
hub = ExsysUsbHub("/dev/ttyUSB0")
hub.connect()
hub.on(2)
hub.close()
```

### From config file

```python
from exsys_hub import ExsysUsbHub, HubConfig

cfg = HubConfig.load("exsys_hub.yaml")

with ExsysUsbHub.from_config(cfg) as hub:
    hub.on(1)
```

---

## Config File

Generate default config:
```bash
python exsys_cli.py config init
```

`exsys_hub.yaml`:
```yaml
device:
  port: /dev/ttyUSB0
  baudrate: 9600
  timeout: 2

ports:
  1: "Z-Wave Dongle"
  2: "Zigbee Coordinator"
  3: ""
  4: ""
```

Manage via CLI:
```bash
python exsys_cli.py config set port /dev/ttyUSB1
python exsys_cli.py config set port-name 1 "Z-Wave Dongle"
python exsys_cli.py config show
```

---

## CLI

```bash
python exsys_cli.py info
python exsys_cli.py status
python exsys_cli.py on  <port>
python exsys_cli.py off <port>
python exsys_cli.py reset
python exsys_cli.py factory-reset
python exsys_cli.py save
```

Override serial port without config:
```bash
python exsys_cli.py -p /dev/ttyUSB0 status
```

---

## Error Handling

```python
from exsys_hub import ExsysUsbHub, HubConnectionError, HubTimeoutError, HubResponseError

try:
    with ExsysUsbHub("/dev/ttyUSB0") as hub:
        hub.on(1)
except HubConnectionError:
    print("Serial port not found or permission denied")
except HubTimeoutError:
    print("Device not responding")
except HubResponseError:
    print("Unexpected response from device")
```
