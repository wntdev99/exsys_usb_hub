"""SerialTransport 검증 — 재연결·재시도·백오프·스레드 안전.

모든 테스트는 FakeSerial 과 주입된 no-op sleep 으로 하드웨어/실제 대기 없이 돈다.
"""

import threading

import pytest
from serial import SerialException

from exsys_usb_hub.core.errors import HubConnectionError, HubTimeoutError
from exsys_usb_hub.core.transport import SerialTransport

from fakes import ConcurrencyProbe, FakeSerial, FakeSerialFactory


def _no_sleep(_):
    pass


def _transport(factory, **kw):
    return SerialTransport(
        "/dev/fake", serial_factory=factory, sleep=_no_sleep, **kw
    )


# ---------------------------------------------------------------------------
# 정상 트랜잭션
# ---------------------------------------------------------------------------
def test_successful_transaction():
    factory = FakeSerialFactory(scripts=[[b"G\r"]])
    t = _transport(factory)
    assert t.transaction(b"GP\r") == "G"
    assert factory.open_calls == 1
    # 명령이 실제로 쓰였고, 쓰기 전에 입력 버퍼를 비웠다.
    ser = factory.instances[0]
    assert ser.written == [b"GP\r"]
    assert ser.input_reset_count == 1


def test_lazy_connect_on_first_transaction():
    """connect() 를 명시 호출하지 않아도 첫 트랜잭션에서 연결된다."""
    factory = FakeSerialFactory(scripts=[[b"G\r"]])
    t = _transport(factory)
    assert t.is_connected is False
    t.transaction(b"GP\r")
    assert t.is_connected is True


# ---------------------------------------------------------------------------
# 재시도 — 타임아웃
# ---------------------------------------------------------------------------
def test_timeout_then_success_reconnects():
    # 첫 연결은 타임아웃(빈 응답), 재연결 후 성공.
    factory = FakeSerialFactory(scripts=[[b""], [b"G\r"]])
    t = _transport(factory, max_retries=2)
    assert t.transaction(b"GP\r") == "G"
    assert factory.open_calls == 2  # 끊고 재연결


def test_timeout_exhausts_retries():
    factory = FakeSerialFactory(scripts=[[b""], [b""], [b""], [b""]])
    t = _transport(factory, max_retries=2)
    with pytest.raises(HubTimeoutError):
        t.transaction(b"GP\r")
    assert factory.open_calls == 3  # 최초 + 재시도 2회


# ---------------------------------------------------------------------------
# 재시도 — 시리얼 예외
# ---------------------------------------------------------------------------
def test_serial_error_during_read_reconnects():
    factory = FakeSerialFactory(scripts=[[SerialException], [b"G\r"]])
    t = _transport(factory, max_retries=2)
    assert t.transaction(b"GP\r") == "G"
    assert factory.open_calls == 2


# ---------------------------------------------------------------------------
# 재시도 — open 실패 후 복구
# ---------------------------------------------------------------------------
def test_open_failure_then_recover():
    factory = FakeSerialFactory(scripts=[[b"G\r"]], open_failures=2)
    t = _transport(factory, max_retries=3)
    assert t.transaction(b"GP\r") == "G"
    assert factory.open_calls == 3  # 실패2 + 성공1


def test_open_failure_exhausted():
    factory = FakeSerialFactory(open_failures=99)
    t = _transport(factory, max_retries=2)
    with pytest.raises(HubConnectionError):
        t.transaction(b"GP\r")


# ---------------------------------------------------------------------------
# 백오프 호출 검증
# ---------------------------------------------------------------------------
def test_backoff_is_exponential_and_capped():
    delays = []
    factory = FakeSerialFactory(scripts=[[b""], [b""], [b""], [b""]])
    t = SerialTransport(
        "/dev/fake", serial_factory=factory, sleep=delays.append,
        max_retries=3, backoff_base=0.1, backoff_cap=0.25,
    )
    with pytest.raises(HubTimeoutError):
        t.transaction(b"GP\r")
    # 0.1, 0.2, min(0.4, 0.25) -> 0.25
    assert delays == [0.1, 0.2, 0.25]


# ---------------------------------------------------------------------------
# 수명주기
# ---------------------------------------------------------------------------
def test_context_manager_opens_and_closes():
    factory = FakeSerialFactory(scripts=[[b"G\r"]])
    with _transport(factory) as t:
        assert t.is_connected is True
        ser = factory.instances[0]
    assert ser.is_open is False
    assert t.is_connected is False


# ---------------------------------------------------------------------------
# 스레드 안전 — 트랜잭션 직렬화
# ---------------------------------------------------------------------------
def test_transactions_are_serialized():
    probe = ConcurrencyProbe()
    t = SerialTransport("/dev/fake", serial_factory=lambda port, **kw: probe,
                        sleep=_no_sleep)
    threads = [threading.Thread(target=lambda: t.transaction(b"GP\r"))
               for _ in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert probe.violations == 0
    assert probe.max_concurrency == 1
