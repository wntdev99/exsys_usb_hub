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
python exsys_cli.py config init                          # 기본 설정 파일 생성
python exsys_cli.py config show                          # 현재 설정 출력
python exsys_cli.py config set port /dev/ttyUSB1        # 시리얼 포트 변경
python exsys_cli.py config set baudrate 9600             # 보드레이트 변경
python exsys_cli.py config set timeout 2                 # 타임아웃 변경
python exsys_cli.py config set port-name 1 "Z-Wave Dongle"  # 포트 이름 설정
```

---

## CLI

```bash
# 장치 제어
python exsys_cli.py info
python exsys_cli.py status
python exsys_cli.py on  <port>
python exsys_cli.py off <port>
python exsys_cli.py reset
python exsys_cli.py factory-reset
python exsys_cli.py save

# 설정 관리
python exsys_cli.py config init
python exsys_cli.py config show
python exsys_cli.py config set port /dev/ttyUSB0
python exsys_cli.py config set port-name 1 "Z-Wave Dongle"
```

Config 없이 시리얼 포트 직접 지정:
```bash
python exsys_cli.py -p /dev/ttyUSB0 status
```

다른 config 파일 지정:
```bash
python exsys_cli.py -c /etc/exsys_hub.yaml status
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
except ValueError:
    print("Invalid port number")  # 포트 범위 초과 시 발생
```
