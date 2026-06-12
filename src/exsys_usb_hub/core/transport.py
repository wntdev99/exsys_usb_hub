"""시리얼 트랜스포트 — 스레드 안전·자동 재연결·재시도.

이 계층은 **프로토콜 의미를 모른다.** "명령 바이트를 쓰고 한 줄 응답을
읽는" 트랜잭션을 신뢰성 있게 수행하는 것만 책임진다. 프로토콜 인코딩/
디코딩은 :mod:`exsys_usb_hub.core.protocol`, 검증·안전정책은 manager 가 맡는다.

복원력 설계
-----------
- **스레드 안전** : 모든 트랜잭션을 ``RLock`` 으로 직렬화한다. ROS2 콜백 등
  여러 스레드가 동시에 호출해도 시리얼 프레임이 섞이지 않는다.
- **자동 재연결** : 연결이 없거나 끊기면 트랜잭션 시점에 지연 재연결한다.
  허브의 존재 이유가 전원 재시작인데, *전원을 끄는 행위 자체가 시리얼
  링크를 흔들 수 있으므로* 재연결은 필수다.
- **지수 백오프 재시도** : 일시적 타임아웃/끊김은 ``max_retries`` 회까지
  재시도하며, 시도 간 대기는 지수적으로 늘어난다(상한 있음).

테스트 용이성
-------------
``serial_factory`` 와 ``sleep`` 을 주입할 수 있어, 하드웨어 없이 FakeSerial
로 단위 테스트가 가능하고 백오프 대기가 테스트를 느리게 만들지 않는다.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

import serial
from serial import SerialException

from .errors import HubConnectionError, HubError, HubTimeoutError

# 시리얼 파라미터 (장치 고정값)
_BYTESIZE = 8
_PARITY = "N"
_STOPBITS = 1


class _SerialPort(Protocol):
    """트랜스포트가 의존하는 시리얼 객체의 최소 인터페이스 (pyserial 호환)."""

    is_open: bool

    def write(self, data: bytes) -> int | None: ...
    def readline(self) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


# serial_factory 시그니처: (port, baudrate, bytesize, parity, stopbits, timeout) -> _SerialPort
SerialFactory = Callable[..., _SerialPort]


def _default_serial_factory(port: str, **kwargs) -> _SerialPort:
    return serial.Serial(port, **kwargs)


class SerialTransport:
    """Exsys 허브와의 신뢰성 있는 요청/응답 시리얼 채널.

    Parameters
    ----------
    port:
        시리얼 포트 경로 (예: ``/dev/exsys_hub``).
    baudrate, timeout:
        시리얼 파라미터. baudrate 는 장치 고정값(9600).
    max_retries:
        트랜잭션 1건당 추가 재시도 횟수 (총 시도 = max_retries + 1).
    backoff_base, backoff_cap:
        지수 백오프 대기의 기준/상한 (초).
    serial_factory:
        시리얼 객체 생성자. 테스트에서 FakeSerial 주입용.
    sleep:
        대기 함수. 테스트에서 즉시 반환하도록 주입 가능.
    logger:
        진단 로그용 ``logging.Logger`` (없으면 모듈 로거).
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        timeout: float = 2.0,
        *,
        max_retries: int = 3,
        backoff_base: float = 0.1,
        backoff_cap: float = 2.0,
        serial_factory: SerialFactory = _default_serial_factory,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._serial_factory = serial_factory
        self._sleep = sleep
        self._log = logger or logging.getLogger(__name__)

        self._ser: _SerialPort | None = None
        # RLock: manager 가 락 보유 중에 다시 트랜잭션을 호출해도 데드락 없음.
        import threading

        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 연결 수명주기
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """시리얼 포트를 연다. 이미 열려 있으면 무시한다."""
        with self._lock:
            self._open()

    def close(self) -> None:
        """시리얼 포트를 닫는다."""
        with self._lock:
            self._drop()

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def __enter__(self) -> "SerialTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 트랜잭션
    # ------------------------------------------------------------------

    def transaction(self, command: bytes) -> str:
        """``command`` 를 쓰고 한 줄 응답을 읽어 strip 한 UTF-8 문자열로 반환한다.

        실패 시 자동 재연결 후 ``max_retries`` 회까지 재시도한다.

        Raises
        ------
        HubConnectionError
            모든 재시도가 끝나도 포트를 열 수 없는 경우.
        HubTimeoutError
            모든 재시도가 끝나도 응답이 없는 경우.
        """
        with self._lock:
            last_exc: HubError | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    self._ensure_open()
                    return self._do_transaction(command)
                except (HubTimeoutError, HubConnectionError) as exc:
                    last_exc = exc
                    self._drop()  # 다음 시도에서 새로 연결
                    if attempt < self._max_retries:
                        self._backoff(attempt)
                        self._log.warning(
                            "트랜잭션 재시도 %d/%d (%s)",
                            attempt + 1, self._max_retries, exc,
                        )
            assert last_exc is not None
            raise last_exc

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _open(self) -> None:
        if self.is_connected:
            return
        try:
            self._ser = self._serial_factory(
                self._port,
                baudrate=self._baudrate,
                bytesize=_BYTESIZE,
                parity=_PARITY,
                stopbits=_STOPBITS,
                timeout=self._timeout,
            )
        except SerialException as exc:
            self._ser = None
            raise HubConnectionError(
                f"시리얼 포트를 열 수 없습니다 {self._port!r}: {exc}"
            ) from exc

    def _ensure_open(self) -> None:
        if not self.is_connected:
            self._open()

    def _drop(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except SerialException:
                pass
        self._ser = None

    def _do_transaction(self, command: bytes) -> str:
        assert self._ser is not None
        try:
            self._ser.reset_input_buffer()  # 이전 잔여 응답 제거 → 프레임 오염 방지
            self._ser.write(command)
            raw = self._ser.readline()
        except SerialException as exc:
            raise HubConnectionError(f"시리얼 통신 실패: {exc}") from exc
        if not raw:
            raise HubTimeoutError("장치 응답 없음 (타임아웃).")
        return raw.decode("utf-8", errors="replace").strip()

    def _backoff(self, attempt: int) -> None:
        delay = min(self._backoff_base * (2 ** attempt), self._backoff_cap)
        self._sleep(delay)

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else "disconnected"
        return f"SerialTransport({self._port!r}, {state})"
