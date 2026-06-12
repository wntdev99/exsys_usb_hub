"""테스트용 시리얼 페이크 — 하드웨어 없이 트랜스포트/매니저를 검증한다."""

from __future__ import annotations

import threading
import time

from serial import SerialException


class FakeSerial:
    """스크립트된 응답을 재생하는 가짜 시리얼 포트.

    ``script`` 의 각 항목이 ``readline()`` 호출마다 순서대로 소비된다:

    - ``bytes``                 : 그대로 반환
    - ``b""``                   : 타임아웃(빈 응답) 시뮬레이션
    - ``Exception`` 인스턴스/클래스 : 해당 예외를 raise (시리얼 오류 시뮬레이션)

    스크립트가 비면 빈 응답(타임아웃)을 반환한다.
    """

    def __init__(self, script=None):
        self.is_open = True
        self._script = list(script or [])
        self.written: list[bytes] = []
        self.input_reset_count = 0

    def reset_input_buffer(self) -> None:
        self.input_reset_count += 1

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def readline(self) -> bytes:
        if not self._script:
            return b""
        item = self._script.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("injected serial error")
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.is_open = False


class FakeSerialFactory:
    """``SerialTransport`` 에 주입하는 가짜 시리얼 생성자.

    Parameters
    ----------
    scripts:
        open 성공 시마다 새 :class:`FakeSerial` 에 넘길 스크립트 리스트.
        재연결마다 다음 스크립트를 사용한다.
    open_failures:
        앞쪽 N 번의 open 을 ``SerialException`` 으로 실패시킨다 (재연결 검증용).
    """

    def __init__(self, scripts=None, open_failures: int = 0):
        self.scripts = list(scripts or [])
        self.open_failures = open_failures
        self.open_calls = 0
        self.instances: list[FakeSerial] = []

    def __call__(self, port, **kwargs) -> FakeSerial:
        self.open_calls += 1
        if self.open_failures > 0:
            self.open_failures -= 1
            raise SerialException("injected open failure")
        script = self.scripts.pop(0) if self.scripts else []
        fs = FakeSerial(script)
        self.instances.append(fs)
        return fs


class ConcurrencyProbe:
    """동시 진입을 감지하는 가짜 시리얼 — Lock 직렬화 검증용."""

    def __init__(self):
        self.is_open = True
        self._active = 0
        self._guard = threading.Lock()
        self.max_concurrency = 0
        self.violations = 0

    def reset_input_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        return len(data)

    def readline(self) -> bytes:
        with self._guard:
            self._active += 1
            self.max_concurrency = max(self.max_concurrency, self._active)
            if self._active > 1:
                self.violations += 1
        time.sleep(0.002)  # 직렬화 안 되면 겹칠 시간
        with self._guard:
            self._active -= 1
        return b"G\r"

    def close(self) -> None:
        self.is_open = False
