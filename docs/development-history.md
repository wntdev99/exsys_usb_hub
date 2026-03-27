# 개발 경위

이 문서는 Exsys USB 허브를 로봇 시스템에서 프로그래밍 방식으로 제어하기까지의 전체 과정을 기록한다.

---

## 1단계 — `uhubctl` 시도 (실패)

USB 포트 전원을 소프트웨어로 제어하는 표준 도구인 `uhubctl`을 먼저 시도했다.

```bash
sudo apt install uhubctl
sudo uhubctl -l 3-6 -p 3 -a off
```

명령은 성공한 것처럼 보였다. 포트 상태가 `0000 off`로 표시됐다. 그러나 실제로는 연결된 장치의 전원이 차단되지 않았다.

**실패 원인:** `uhubctl`이 지원하는 허브 목록([github.com/mvp/uhubctl](https://github.com/mvp/uhubctl))에 이 허브가 없었다. Exsys 관리형 허브는 USB 프로토콜의 PPPS(Per-Port Power Switching) 명령으로 VL817 칩 레지스터를 바꾸더라도 실제 VBUS 스위치는 내부 MCU가 시리얼 인터페이스를 통해서만 제어한다. 자세한 원인 분석은 [uhubctl-vbus-analysis.md](uhubctl-vbus-analysis.md)를 참고한다.

---

## 2단계 — 공식 소프트웨어 발견 및 동작 확인

Exsys 제품 페이지([exsys.ch EX-1504HMS](https://www.exsys.ch/en/managed-4-port-usb-3.2-gen-1-metal-hub-with-15kv-esd-surge-protection-din-rail-EX-1504HMS))의 Downloads 섹션에서 **Management Software USB HUB - Linux** 파일을 발견했다.

다운로드한 `cusbi-r1.03.tar.gz`를 열어보니 내부에 바이너리 실행 파일 `cusbi`가 있었다. 실행해보니 포트 전원 제어가 정상 동작함을 확인했다.

**문제:** `cusbi`는 컴파일된 바이너리다. 로봇 시스템에서 자율적으로 허브를 제어하려면 Python 코드에서 `subprocess`로 외부 프로세스를 실행해야 하는 구조적 한계가 있었다. 에러 처리, 상태 조회, 로깅 등을 연동하기 어렵고, 배포 및 유지보수도 불편했다.

---

## 3단계 — Home Assistant 통합 소스코드 발견

시리얼 프로토콜이 이미 구현된 오픈소스를 찾던 중 Home Assistant 통합 컴포넌트([github.com/veista/exsys_usb_hub](https://github.com/veista/exsys_usb_hub))를 발견했다.

이 소스코드는 시리얼 프로토콜(`?Q`, `GP`, `SPpass...` 커맨드)을 완전히 구현하고 있었다. 단, Home Assistant 플랫폼에 강하게 결합된 구조였다.

**원본 구조의 한계:**
- `homeassistant.core.HomeAssistant`를 생성자에서 직접 주입받음
- `serial_asyncio_fast` 기반의 비동기 전용 설계 — HA 이벤트 루프에 종속
- HA 엔티티(`SwitchEntity`) 구조에 묶여 있어 독립 실행 불가
- 설정, 에러 처리, CLI 없음

---

## 4단계 — 리팩토링: 순수 Python 모듈로 재작성

원본을 fork하여 HA 의존성을 완전히 제거하고 독립 실행 가능한 Python 패키지로 재작성했다.

### 의존성 제거

| 원본 | 변경 후 |
|---|---|
| `homeassistant.core.HomeAssistant` | 제거 |
| `serial_asyncio_fast` (비동기) | `pyserial` (동기) |
| HA 이벤트 루프 | 불필요 |
| `SwitchEntity`, `ExsysUsbHubEntity` | 제거 |

### 핵심 드라이버 (`exsys_hub/hub.py`)

`archive/custom_components/exsys_usb_hub/device.py`의 `Device` 클래스를 기반으로 `ExsysUsbHub`로 재작성했다. 주요 변경점:

- **동기 시리얼 통신으로 전환** — `asyncio` 없이 어디서든 호출 가능
- **context manager 지원** — `with ExsysUsbHub(...) as hub:` 패턴
- **에러 계층 구조화** — `HubError` / `HubConnectionError` / `HubTimeoutError` / `HubResponseError`로 세분화
- **프로토콜 함수 분리** — `_parse_hub_ports`, `_message_from_hub_ports`를 클래스 외부 순수 함수로 추출해 테스트 가능하게 변경
- **classmethod 팩토리** — `ExsysUsbHub.from_config(cfg)` 추가

### 시리얼 프로토콜 (원본에서 유지)

원본에서 검증된 프로토콜 구현은 그대로 유지했다.

| 커맨드 | 동작 |
|---|---|
| `?Q\r` | 모델명 / 포트 수 / 펌웨어 버전 조회 |
| `GP\r` | 전체 포트 상태 조회 |
| `SPpass    <hex>\r` | 포트 상태 일괄 설정 |
| `RHpass    \r` | 허브 리셋 |
| `RDpass    \r` | 공장 초기화 |
| `WPpass    \r` | 현재 상태를 기본값으로 저장 |

### 설정 파일 (`exsys_hub/config.py`)

YAML 기반 `HubConfig` 추가. 시리얼 포트 경로, 보드레이트, 타임아웃, 포트 이름을 파일로 관리한다.

```yaml
device:
  port: /dev/exsys_hub
  baudrate: 9600
  timeout: 2

ports:
  1: "Z-Wave Dongle"
  2: "Orbbec Camera"
```

### CLI (`exsys_cli.py`)

터미널에서 직접 사용하거나 로봇 시스템의 launch 스크립트에서 호출할 수 있는 CLI를 추가했다.

```bash
python exsys_cli.py status
python exsys_cli.py on 2
python exsys_cli.py off 2
```

---

## 5단계 — 시스템 통합 자동화 (`setup.sh`)

로봇 시스템에 도입할 때마다 수동 설정을 반복하지 않도록 설치 자동화 스크립트를 작성했다.

`setup.sh` 실행 한 번으로 아래를 모두 처리한다:

| 단계 | 내용 |
|---|---|
| 플랫폼 검사 | Linux / Python 3.10+ / WSL 감지 |
| 패키지 설치 | `pip install -e .` (editable, `--no-deps`) |
| 장치 감지 | 연결된 USB-Serial 장치 VID/PID/Serial 자동 탐색 |
| udev 규칙 생성 | `/etc/udev/rules.d/99-exsys-hub.rules` |
| 심링크 생성 | `/dev/exsys_hub` 고정 경로 (USB 포트 변경 무관) |
| 권한 설정 | `MODE=0666` — sudo 없이 즉시 사용 가능 |
| 설정 파일 생성 | `exsys_hub.yaml` 기본값으로 생성 |

udev 심링크(`/dev/exsys_hub`)를 사용하면 USB 포트를 다른 슬롯에 꽂아도 코드 수정 없이 동작한다.

---

## 결과

```python
from exsys_hub import ExsysUsbHub

with ExsysUsbHub("/dev/exsys_hub") as hub:
    hub.off(2)   # 카메라 전원 차단
    hub.on(2)    # 카메라 전원 복구
```

로봇 프로세스가 스스로 판단해 특정 USB 장치의 전원을 껐다 켤 수 있는 구조가 완성됐다.
