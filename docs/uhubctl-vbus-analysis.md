# `uhubctl`로 VBUS 제어가 되지 않는 이유

`uhubctl`은 명령이 성공했다고 보고하지만, Exsys 관리형 허브에서는 실제 VBUS(전원 라인)가 차단되지 않는다.

---

## 허브의 하드웨어 구조

이 허브는 호스트에 **두 개의 독립적인 제어 채널**을 노출한다.

```
lsusb 출력:
  2109:0817  VIA Labs VL817  — USB 3.0 허브 칩셋   (USB 프로토콜)
  0403:6001  FTDI FT232R     — 시리얼 UART          (시리얼 프로토콜 → 내부 MCU)
```

일반 범용 USB 허브는 하나의 칩셋만 존재하지만, Exsys 관리형 허브는 USB 칩셋과 별도로 시리얼로 통신하는 내부 MCU를 탑재하고 있다.

---

## `uhubctl`이 하는 일

`uhubctl`은 **USB 허브 클래스 프로토콜** (USB spec §11.5 `ClearPortFeature(PORT_POWER)`)을 사용해 VL817 칩의 내부 레지스터를 변경한다.

```
uhubctl -l 3-6 -p 3 -a off
  → USB Control Transfer: ClearPortFeature(PORT_POWER)
  → VL817 내부 레지스터: Port Power 비트 = 0
  → uhubctl 보고: "Port 3: 0000 off"   ← 레지스터 수준의 성공일 뿐
```

레지스터 값이 바뀌었기 때문에 명령은 "성공"으로 처리된다. `uhubctl`이 동작한 것처럼 보이는 이유다.

---

## 실제 VBUS가 차단되지 않는 이유

**일반 허브**에서는 VL817의 PPPS(Per-Port Power Switching) 출력 핀이 VBUS 스위치(MOSFET)를 직접 구동한다. **Exsys 관리형 허브**는 회로 구성이 다르다.

```
일반 허브:
  VL817 PPPS 출력 핀 → VBUS MOSFET → VBUS 차단 ✓

Exsys 관리형 허브:
  VL817 PPPS 출력 핀
      ↓ (VBUS 스위치에 연결되지 않음)
      ✗ VBUS MOSFET

  FT232R → 내부 MCU
      ↓ (SP 커맨드 수신 시)
      ✓ VBUS MOSFET → 실제 전원 차단
```

VL817 레지스터는 변경되지만, 실제 VBUS 스위치는 시리얼 관리 인터페이스를 통한 내부 MCU만이 제어한다. `uhubctl`은 그 경로에 전혀 접근하지 않는다.

---

## 출력에서 확인할 수 있는 근거

`off` → `on` 사이클 후 해당 포트 상태:

```
Port 3: 0101 power connect []
                            ^^
                    장치명이 비어 있음
```

VBUS가 실제로 차단됐다가 복구됐다면 장치가 재열거되어 아래처럼 표시돼야 한다:

```
Port 3: 0507 power highspeed enable connect [2bc5:0803 Orbbec Gemini 336 ...]
```

`[]`(빈칸)은 장치가 전원 사이클을 겪지 않았음을 의미한다. USB 신호 레벨에서만 잠깐 흔들렸을 뿐, VBUS는 내내 공급 중이었다.

---

## 제어 방식 비교

|  | `uhubctl` | `exsys_hub` (이 패키지) |
|---|---|---|
| 제어 경로 | USB 프로토콜 → VL817 레지스터 | 시리얼 → FT232R → 내부 MCU |
| VL817 레지스터 변경 | ✓ | ✗ (우회) |
| VBUS 물리적 차단 | ✗ | ✓ |
| 장치 재열거 | ✗ (`[]` 빈칸) | ✓ (정상 재인식) |

---

## 결론

Exsys 관리형 허브에서 실제 VBUS 스위칭은 FT232R 시리얼 인터페이스를 통해 `SPpass...` 커맨드를 내부 MCU에 전달해야만 이루어진다. 이 패키지가 그 경로를 구현한다.
