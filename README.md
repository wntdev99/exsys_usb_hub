# Exsys USB Hub

Home Assistant용 Exsys 관리형 USB 허브 통합 컴포넌트

USB-Serial 관리 방식을 사용하는 Exsys 관리형 USB 허브(4~16포트)를 지원합니다.
EX-1504HMS 모델로 테스트되었습니다.

Z-Wave 동글처럼 불안정한 USB 장치를 원격으로 전원 사이클링하거나, 자동화 복구가 필요한 환경에서 특히 유용합니다.

![image](https://github.com/user-attachments/assets/3e85e21f-c66d-4eea-877f-a36e4989f86e)

---

## 요구 사항

| 항목 | 버전 |
|------|------|
| Home Assistant | 2024.5.3 이상 |
| Python 패키지 | `pyserial`, `pyserial-asyncio-fast` (HA가 자동 설치) |
| 하드웨어 | USB-Serial 관리 포트가 있는 Exsys 관리형 USB 허브 |

---

## 설치 방법

### 방법 1: HACS (권장)

1. Home Assistant에서 **HACS** → **Integrations** 이동
2. 우측 상단 메뉴(⋮) → **Custom repositories** 클릭
3. URL에 `https://github.com/veista/exsys_usb_hub` 입력, 카테고리는 **Integration** 선택 후 추가
4. HACS 통합 목록에서 **Exsys USB Hub** 검색 후 **Download**
5. Home Assistant 재시작

### 방법 2: 수동 설치

```bash
# Home Assistant 설정 디렉토리로 이동
cd /config

# custom_components 디렉토리가 없으면 생성
mkdir -p custom_components

# 이 저장소 클론
git clone https://github.com/veista/exsys_usb_hub.git /tmp/exsys_usb_hub

# 컴포넌트 파일 복사
cp -r /tmp/exsys_usb_hub/custom_components/exsys_usb_hub custom_components/
```

복사 후 Home Assistant를 재시작합니다.

---

## 설정 방법

### 1. 하드웨어 연결 확인

허브의 USB-Serial 관리 포트를 HA 호스트에 연결한 뒤, 시리얼 포트 경로를 확인합니다.

**Linux/HA OS:**
```bash
ls /dev/ttyUSB* /dev/ttyACM*
# 예시 출력: /dev/ttyUSB0
```

**HA Container/Supervised 환경:** 호스트에서 확인 후 해당 경로를 HA에 패스스루(passthrough) 설정

### 2. 통합 추가

1. **Settings** → **Devices & Services** → **Add Integration**
2. **Exsys USB Hub** 검색 후 선택
3. 설정 폼 입력:

| 항목 | 설명 | 예시 |
|------|------|------|
| Device Name | 허브 표시 이름 | `Exsys USB Hub` |
| Path | 시리얼 포트 경로 | `/dev/ttyUSB0` |

4. 연결 검증 후 자동으로 포트 수를 감지하여 엔티티 생성

---

## 생성되는 엔티티

### Switch (포트당 1개)

| 엔티티 ID 예시 | 설명 |
|---------------|------|
| `switch.exsys_usb_hub_port_1` | USB 포트 1 전원 제어 |
| `switch.exsys_usb_hub_port_2` | USB 포트 2 전원 제어 |
| ... | (포트 수만큼 자동 생성) |

### Button (3개, 설정 카테고리)

| 엔티티 | 동작 |
|--------|------|
| `button.exsys_usb_hub_reset` | 허브 전체 리셋 |
| `button.exsys_usb_hub_restore_factory_defaults` | 공장 초기화 |
| `button.exsys_usb_hub_save_port_states` | 현재 포트 상태를 시작 기본값으로 저장 |

---

## 자동화 예시

### Z-Wave 동글 자동 복구

```yaml
automation:
  - alias: "Z-Wave 동글 재시작"
    trigger:
      - platform: state
        entity_id: binary_sensor.zwave_network_healthy
        to: "off"
        for: "00:02:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.exsys_usb_hub_port_1
      - delay: "00:00:05"
      - service: switch.turn_on
        target:
          entity_id: switch.exsys_usb_hub_port_1
```

### 야간 USB 포트 전원 절약

```yaml
automation:
  - alias: "야간 USB 포트 끄기"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id:
            - switch.exsys_usb_hub_port_2
            - switch.exsys_usb_hub_port_3
```

---

## 통신 프로토콜

장치와의 통신은 시리얼(9600 baud, 8N1)로 이루어집니다.

| 명령 | 동작 |
|------|------|
| `?Q\r` | 장치 정보 조회 (모델, 포트 수, 펌웨어) |
| `GP\r` | 현재 포트 상태 조회 |
| `SPpass    <hex>\r` | 포트 상태 설정 |
| `RHpass    \r` | 허브 리셋 |
| `RDpass    \r` | 공장 초기화 |
| `WPpass    \r` | 현재 상태를 시작 기본값으로 저장 |

---

## 문제 해결

### 연결 실패 (cannot_connect)

- 시리얼 포트 경로가 올바른지 확인 (`/dev/ttyUSB0` 등)
- HA 프로세스가 해당 포트에 접근 권한이 있는지 확인
  ```bash
  # HA OS: 일반적으로 자동 허용
  # Docker: --device=/dev/ttyUSB0 옵션 필요
  ls -l /dev/ttyUSB0
  # crw-rw---- 1 root dialout ...  → HA 실행 사용자가 dialout 그룹인지 확인
  ```
- 허브의 USB-Serial 관리 포트가 올바르게 연결되었는지 확인

### 잘못된 응답 (invalid_response)

- 연결된 장치가 Exsys 관리형 USB 허브가 맞는지 확인
- 다른 프로그램이 해당 시리얼 포트를 점유하고 있지 않은지 확인

### HA 로그 확인

```yaml
# configuration.yaml에 추가하여 디버그 로그 활성화
logger:
  default: warning
  logs:
    custom_components.exsys_usb_hub: debug
```

---

## 지원 및 이슈

- 이슈 제출 전 [기존 이슈](https://github.com/veista/exsys_usb_hub/issues?q=) 및 [디스커션](https://github.com/veista/exsys_usb_hub/discussions) 확인
- [릴리스 노트](https://github.com/veista/exsys_usb_hub/releases) 참조

이 통합이 유용하다면 별(⭐)을 남겨주세요.
