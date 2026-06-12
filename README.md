# exsys_usb_hub

Exsys 관리형 USB 허브(EX-1504HMS 등, 4–16포트)의 포트 전원을 시리얼로 제어하는 **ROS2 패키지**.

**핵심 구조**: ROS 비의존 코어(프로토콜·시리얼·안전정책) 위에 ROS2 Lifecycle 노드를 얹은 계층형. 코어는 ROS 없이 노트북·CLI·테스트에서 그대로 동작하고, 로봇에서는 노드로 통합된다.

**검증 환경**: ROS2 Jazzy, Python 3.10+, Ubuntu 22.04+. 장치: EX-1504HMS (관리 인터페이스 FTDI FT232R `0403:6001`).

---

## 아키텍처

```
─ ROS-free 코어 (rclpy 모름, 독립 동작) ──────────────
  core/protocol.py   순수 코덱 (encode/decode/parse) — 골든벡터+라운드트립 테스트
  core/transport.py  시리얼 Lock·자동재연결·백오프·재시도
  core/manager.py    read-back 검증 + 안전정책(보호포트·인러시지연) + 다중허브 훅
  core/config.py     YAML 설정
  cli.py             ROS 없는 CLI
─ ROS2 어댑터 (코어를 import만) ──────────────────────
  ros/node.py        Lifecycle 노드: 서비스·토픽·진단
```

---

## 설치

```bash
cd <your_ros2_ws>/src
git clone <repo-url> exsys_usb_hub
cd exsys_usb_hub
sudo bash setup.sh
```

`setup.sh`가 자동 처리하는 항목:

| 항목 | 내용 |
|------|------|
| 플랫폼 검사 | Linux / Python 3.10+ / WSL 감지 / ROS2 환경 |
| 장치 감지 | 연결된 USB-Serial 장치 탐색 (다중 선택 가능) |
| udev 규칙 | `/etc/udev/rules.d/99-exsys-hub.rules` 생성 |
| 심링크 | per-serial 고정 경로 — 단일: `/dev/exsys_hub`, 다중: `/dev/exsys_hub-<serial>` |
| 권한 | `MODE=0666` — sudo 없이 즉시 사용 |
| 빌드 | `colcon build --packages-select exsys_usb_hub` |

> per-serial 심링크를 쓰는 이유: 관리 인터페이스가 범용 FTDI FT232R(`0403:6001`)이라 VID:PID로는 허브를 구분할 수 없고, FT232R의 serial이 유일한 고유 식별자다. serial 기반이라 USB 슬롯을 바꿔도, 다른 FTDI 장치가 섞여 있어도 안전하다.

수동 빌드:
```bash
cd <your_ros2_ws>
colcon build --packages-select exsys_usb_hub
source install/setup.bash
```

---

## ROS2 사용

**단일 노드가 1개 이상의 허브를 관리**하고, 포트는 **이름**(전역 고유)으로 제어한다. 허브가 1개든 N개든 같은 노드·launch·서비스를 쓴다. 외부 호출자는 허브 위치를 몰라도 포트 이름만으로 제어한다.

### 설정 (`config/exsys_hub_multi.yaml`)

허브 목록을 적는다. 1개면 항목 1개, 여러 개면 여러 항목. `device_path`는 setup.sh가 만든 per-serial 심링크로 채운다.

```yaml
hubs:
  - name: hub_bottom
    device_path: /dev/exsys_hub-BG02Y51S    # setup.sh --list 로 확인한 심링크
    protected_ports: []
    inrush_delay_ms: 500
    port_names: ["handeye_camera", "bottom_camera", "front_camera", ""]   # 빈칸=미사용
  - name: hub_top
    device_path: /dev/exsys_hub-BG0317MR
    port_names: ["switching_hub", "right_camera", "rear_camera", "left_camera"]
```

> 포트 이름은 **모든 허브에서 전역 고유**해야 한다(중복 시 configure 실패). 빈 이름("")은 제어 대상에서 제외된다.

### 기동

```bash
ros2 launch exsys_usb_hub exsys_hub.launch.py
ros2 launch exsys_usb_hub exsys_hub.launch.py config:=/path/to/hubs.yaml
```

Lifecycle 노드를 띄우고 자동으로 configure→activate한다 (`auto_start:=false`로 수동 제어).

### 서비스 — 이름으로 제어

```bash
# 포트 이름으로 ON/OFF (어느 허브인지 몰라도 됨)
ros2 service call /exsys_hub_node/set_port exsys_usb_hub_msgs/srv/SetPort \
  "{port: 'handeye_camera', state: false}"

# 전체 허브 대상 관리 명령
ros2 service call /exsys_hub_node/reset         std_srvs/srv/Trigger
ros2 service call /exsys_hub_node/factory_reset std_srvs/srv/Trigger
ros2 service call /exsys_hub_node/save          std_srvs/srv/Trigger
```

보호 포트(`protected_ports`)에 매핑된 이름을 OFF하려 하면 `success: false`로 거부한다.

### 토픽 — 이름 포함 상태

```bash
ros2 topic echo /exsys_hub_node/hub_status   # exsys_usb_hub_msgs/HubStatus (이름 포함, latched)
# ports:
#   - {hub: hub_top, index: 4, name: left_camera, on: true}
ros2 topic echo /diagnostics                 # diagnostic_msgs/DiagnosticArray (허브별 진단)
```

### 허브별 파라미터 (config 항목당)

| 키 | 기본값 | 설명 |
|---|---|---|
| `device_path` | — | 시리얼 포트 (udev 심링크) |
| `baudrate` | `9600` | 장치 고정값 |
| `poll_rate_hz` | `1.0` | 상태 폴링 주기 |
| `protected_ports` | `[]` | OFF 거부 포트 번호 |
| `inrush_delay_ms` | `500` | OFF→ON 사이 최소 대기 |
| `verify_retries` | `2` | set 후 read-back 검증 재시도 |
| `port_names` | `[]` | 포트 이름(전역 고유, 제어 키) |

> `ros2 launch ... exsys_hub_multi.launch.py` 도 동일하게 동작한다(통합 launch의 하위호환 별칭).

---

## CLI (ROS 불필요)

```bash
ros2 run exsys_usb_hub exsys_cli status
ros2 run exsys_usb_hub exsys_cli on 1
ros2 run exsys_usb_hub exsys_cli off 2
ros2 run exsys_usb_hub exsys_cli -p /dev/exsys_hub info

# 설정 관리
ros2 run exsys_usb_hub exsys_cli config init
ros2 run exsys_usb_hub exsys_cli config set port-name 1 "Z-Wave Dongle"
```

CLI는 코어만 쓰므로 ROS 없이도 동작한다 (빌드 후 `install/.../lib/exsys_usb_hub/exsys_cli` 직접 실행 가능).

---

## 라이브러리로 사용 (ROS 불필요)

```python
from exsys_usb_hub.core import HubManager, SerialTransport

transport = SerialTransport("/dev/exsys_hub")
with HubManager(transport, protected_ports=[1], inrush_delay_s=0.5) as hub:
    print(hub.info())      # HubInfo(model=..., n_ports=4, firmware='v04')
    print(hub.status())    # [True, True, False, False]
    hub.off(2)             # 포트 2 OFF (보호 포트면 SafetyViolation)
    hub.power_cycle(2)     # OFF → 인러시 지연 → ON
```

### 예외 계층

```python
from exsys_usb_hub.core import (
    HubError, HubConnectionError, HubTimeoutError,
    HubResponseError, ProtocolError, SafetyViolation,
)
```

모든 예외는 `HubError`를 상속하므로 `except HubError`로 일괄 처리 가능하다.

---

## 테스트

```bash
# ROS 없이 코어/CLI 테스트
python3 -m pytest test/ -q
# 또는 colcon
colcon test --packages-select exsys_usb_hub
```

프로토콜 코덱은 원본 구현에서 캡처한 골든 벡터 + 라운드트립 전수(n=4·7·8·16)로 동결돼 있다. rclpy 부재 시 노드 테스트만 자동 skip된다.

---

## 참고

- [개발 경위](docs/development-history.md) — uhubctl 시도부터 ROS2 패키지 리팩토링까지 전체 과정
- [`uhubctl`로 VBUS 제어가 되지 않는 이유](docs/uhubctl-vbus-analysis.md)
