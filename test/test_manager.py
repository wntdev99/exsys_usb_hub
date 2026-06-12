"""HubManager 검증 — 고수준 API + 안전 정책 + read-back 검증.

실제 프로토콜을 흉내내는 FakeHubSerial 위에서 동작하므로, 코덱·트랜스포트·
매니저가 함께 올바르게 맞물리는지 통합 수준으로 검증한다.
"""

import pytest

from exsys_usb_hub.core.errors import HubResponseError, SafetyViolation
from exsys_usb_hub.core.manager import HubManager
from exsys_usb_hub.core.transport import SerialTransport

from fakes import FakeHubSerial


def _manager(hub, **mgr_kw):
    """주어진 FakeHubSerial 에 연결된 연결-완료 상태의 HubManager 를 만든다."""
    transport = SerialTransport(
        "/dev/fake", serial_factory=lambda port, **kw: hub, sleep=lambda d: None
    )
    mgr = HubManager(transport, sleep=lambda d: None, **mgr_kw)
    mgr.connect()
    return mgr


# ---------------------------------------------------------------------------
# 정보 / 상태 조회
# ---------------------------------------------------------------------------
def test_info_parsed_from_device():
    mgr = _manager(FakeHubSerial(n_ports=4))
    info = mgr.info()
    assert info.model == "CENTOS000104"
    assert info.n_ports == 4
    assert info.firmware == "v04"


def test_status_reflects_device_state():
    mgr = _manager(FakeHubSerial(states=[True, False, True, False]))
    assert mgr.status() == [True, False, True, False]
    assert mgr.get_port(1) is True
    assert mgr.get_port(2) is False


# ---------------------------------------------------------------------------
# 제어 + read-back 검증
# ---------------------------------------------------------------------------
def test_on_off_updates_and_verifies():
    hub = FakeHubSerial(states=[False, False, False, False])
    mgr = _manager(hub)
    assert mgr.on(2) is True
    assert hub.states == [False, True, False, False]
    assert mgr.get_port(2) is True
    mgr.off(2)
    assert hub.states == [False, False, False, False]


def test_set_port_retries_on_flaky_device():
    """첫 SP 가 상태를 안 바꿔도(검증 실패) 재시도해서 성공한다."""
    hub = FakeHubSerial(states=[False] * 4, flaky_sets=1)
    mgr = _manager(hub, verify_retries=2)
    assert mgr.on(1) is True
    assert hub.states[0] is True


def test_set_port_raises_when_verify_never_succeeds():
    hub = FakeHubSerial(states=[False] * 4, flaky_sets=99)
    mgr = _manager(hub, verify_retries=2)
    with pytest.raises(HubResponseError):
        mgr.on(1)


# ---------------------------------------------------------------------------
# 안전 정책 — 보호 포트
# ---------------------------------------------------------------------------
def test_protected_port_refuses_off():
    hub = FakeHubSerial(states=[True, True, False, False])
    mgr = _manager(hub, protected_ports=[1])
    with pytest.raises(SafetyViolation):
        mgr.off(1)
    assert hub.states[0] is True  # 상태 변화 없음


def test_protected_port_still_allows_on():
    hub = FakeHubSerial(states=[False, False, False, False])
    mgr = _manager(hub, protected_ports=[1])
    assert mgr.on(1) is True  # ON 은 막지 않음
    assert hub.states[0] is True


# ---------------------------------------------------------------------------
# 안전 정책 — 인러시 지연
# ---------------------------------------------------------------------------
def test_inrush_delay_enforced_on_off_then_on():
    hub = FakeHubSerial(states=[True, False, False, False])
    clock = {"t": 100.0}
    slept = []
    transport = SerialTransport(
        "/dev/fake", serial_factory=lambda port, **kw: hub, sleep=lambda d: None
    )
    mgr = HubManager(
        transport, inrush_delay_s=0.5,
        monotonic=lambda: clock["t"], sleep=slept.append,
    )
    mgr.connect()

    mgr.off(1)            # last_off = 100.0
    clock["t"] = 100.2    # 0.2s 경과 (지연 0.5s 미달)
    mgr.on(1)
    # 남은 0.3s 만큼 대기해야 한다.
    assert slept and abs(slept[-1] - 0.3) < 1e-9


def test_no_inrush_wait_when_enough_time_passed():
    hub = FakeHubSerial(states=[True, False, False, False])
    clock = {"t": 100.0}
    slept = []
    transport = SerialTransport(
        "/dev/fake", serial_factory=lambda port, **kw: hub, sleep=lambda d: None
    )
    mgr = HubManager(
        transport, inrush_delay_s=0.5,
        monotonic=lambda: clock["t"], sleep=slept.append,
    )
    mgr.connect()
    mgr.off(1)
    clock["t"] = 101.0    # 1.0s 경과 (지연 충분)
    mgr.on(1)
    assert slept == []    # 대기 없음


# ---------------------------------------------------------------------------
# 포트 범위 검증
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("port", [0, 5, -1])
def test_invalid_port_raises(port):
    mgr = _manager(FakeHubSerial(n_ports=4))
    with pytest.raises(ValueError):
        mgr.on(port)


# ---------------------------------------------------------------------------
# 리셋 / 저장
# ---------------------------------------------------------------------------
def test_factory_reset_returns_states():
    mgr = _manager(FakeHubSerial(states=[True, True, True, True]))
    assert mgr.factory_reset() == [True, True, True, True]


def test_save_ok():
    mgr = _manager(FakeHubSerial())
    mgr.save()  # 예외 없으면 성공
