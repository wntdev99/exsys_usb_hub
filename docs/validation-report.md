# 검증 보고서 — Exsys USB Hub 전원 제어

## 1. 검증할 정량지표 리스트

| # | 지표 | 기준 |
|---|---|---|
| 1 | VBUS 실제 차단 여부 | 전원 OFF 명령 후 장치가 호스트에서 완전히 사라질 것 |
| 2 | 장치 재열거 성공률 | 전원 ON 복구 후 장치명이 정상 표시될 것 (`[]` 아닐 것) |
| 3 | 시리얼 응답 정상 여부 | `SPpass...` 커맨드에 대해 허브가 `G`(Good) 응답 반환할 것 |
| 4 | sudo 없이 접근 가능 여부 | `MODE=0666` udev 규칙 적용 후 일반 사용자 권한으로 동작할 것 |
| 5 | 포트 경로 고정 여부 | USB 슬롯 변경 후에도 `/dev/exsys_hub` 심링크 유효할 것 |

---

## 2. 결과

| # | 지표 | 결과 |
|---|---|---|
| 1 | VBUS 실제 차단 | `uhubctl` ✗ / `exsys_hub` ✓ |
| 2 | 장치 재열거 성공률 | `uhubctl` 0% (`[]` 빈칸) / `exsys_hub` 100% (정상 재인식) |
| 3 | 시리얼 응답 정상 여부 | ✓ (`G` 응답 확인) |
| 4 | sudo 없이 접근 | ✓ (udev `MODE=0666` 적용 완료) |
| 5 | 포트 경로 고정 | ✓ (`/dev/exsys_hub` 심링크 생성 확인) |

**최종 결론:** `exsys_hub` 패키지를 통한 시리얼 직접 제어 방식이 유효하다. VBUS 실제 차단 및 장치 재열거가 정상 동작하며, 로봇 시스템에서 sudo 없이 호출 가능한 상태로 도입 완료.

**검증 영상:** [exsys_hub_validation_demo.mp4](exsys_hub_validation_demo.mp4)

---

## 3. 케이스

**테스트 대상 장치:**
- 허브: Exsys EX-1504HMS (VIA Labs VL817, USB 3.2 Gen1, 4포트)
- 제어 대상 포트: Port 3
- 연결 장치: Orbbec Gemini 336 (`2bc5:0803`, USB 2.0 HighSpeed)
- 관리 인터페이스: FTDI FT232R (`0403:6001`, `/dev/ttyUSB0`)

**시나리오 A — `uhubctl` 전원 제어 (실패 케이스)**
```
sudo uhubctl -l 3-6 -p 3 -a off  →  sudo uhubctl -l 3-6 -p 3 -a on
```
Ubuntu 22.04, 상온, 노트북 직결 환경에서 1회 실시.

**시나리오 B — `exsys_hub` 시리얼 전원 제어 (성공 케이스)**
```python
hub.off(3)  →  hub.on(3)
```
동일 환경, 시리얼 포트 `/dev/ttyUSB0`, baudrate 9600, timeout 2s.

---

## 4. 과정 및 분석 내용 정리

### 시나리오 A — `uhubctl` 결과

| 단계 | 명령 | hub 3-6 Port 3 상태 | hub 2-2 Port 3 상태 | 장치 인식 |
|---|---|---|---|---|
| 초기 | — | `0507` power highspeed enable connect | `02a0` power 5gbps Rx.Detect | Orbbec Gemini 336 ✓ |
| OFF 후 | `-a off` | `0000` off | `00a0` off | — |
| ON 후 | `-a on` | `0101` power connect `[]` | `02a0` power 5gbps Rx.Detect | **빈칸 — 재열거 실패** |

- `off` 시 레지스터는 정상 변경됐으나 VBUS는 물리적으로 유지됨
- `on` 후 `connect`는 표시되나 장치명이 `[]` — 전원 사이클이 없었으므로 재열거 트리거 없음
- **결론: VBUS 차단 없이 USB 신호 레벨만 흔들린 것**

### 시나리오 B — `exsys_hub` 결과

| 단계 | 커맨드 | 허브 응답 | 장치 인식 |
|---|---|---|---|
| OFF | `SPpass    <hex>\r` | `G` (Good) | 장치 완전 소멸 ✓ |
| ON | `SPpass    <hex>\r` | `G` (Good) | Orbbec Gemini 336 재열거 ✓ |

- 시리얼 MCU가 VBUS MOSFET를 직접 제어 → 실제 전원 차단
- 복구 후 장치가 정상 재열거됨

### 도구별 제어 경로 비교

```
uhubctl:
  USB Control Transfer → VL817 레지스터 변경
                      ↛ VBUS MOSFET  (연결 없음)

exsys_hub:
  pyserial → FT232R → 내부 MCU → VBUS MOSFET → 실제 차단
```
