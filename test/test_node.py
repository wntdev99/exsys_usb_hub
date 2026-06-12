"""ExsysHubNode 검증 — lifecycle 전이 + 서비스 콜백.

rclpy 가 필요하다(없으면 skip). FakeHubSerial 기반 매니저를 주입해
하드웨어 없이 노드 로직을 검증한다. 전이 콜백(on_configure/on_activate)을
직접 호출하므로 executor 스핀 없이도 동작을 확인할 수 있다.
"""

import pytest

rclpy = pytest.importorskip("rclpy")

from rclpy.lifecycle import TransitionCallbackReturn  # noqa: E402
from std_srvs.srv import SetBool, Trigger  # noqa: E402

from exsys_usb_hub.core import HubManager, SerialTransport  # noqa: E402
from exsys_usb_hub.ros.node import ExsysHubNode  # noqa: E402

from fakes import FakeHubSerial, FakeSerialFactory  # noqa: E402


@pytest.fixture(autouse=True)
def _rclpy():
    rclpy.init()
    yield
    rclpy.shutdown()


def _make_node(hub=None, **mgr_kw):
    """FakeHubSerial 기반 매니저를 주입한 노드를 만든다."""
    hub = hub or FakeHubSerial(n_ports=4)

    def factory():
        transport = SerialTransport(
            "/dev/fake", serial_factory=lambda port, **kw: hub, sleep=lambda d: None
        )
        return HubManager(transport, sleep=lambda d: None, **mgr_kw)

    return ExsysHubNode(manager_factory=factory), hub


def test_configure_connects_and_creates_services():
    node, hub = _make_node()
    try:
        assert node.on_configure(None) == TransitionCallbackReturn.SUCCESS
        assert len(node._set_srvs) == 4  # 포트당 1개
        assert node._reset_srv is not None
    finally:
        node.destroy_node()


def test_configure_fails_when_device_absent():
    """연결 불가 시 on_configure 가 FAILURE 를 반환한다."""
    def factory():
        transport = SerialTransport(
            "/dev/fake",
            serial_factory=FakeSerialFactory(open_failures=99),
            sleep=lambda d: None, max_retries=1,
        )
        return HubManager(transport, sleep=lambda d: None)

    node = ExsysHubNode(manager_factory=factory)
    try:
        assert node.on_configure(None) == TransitionCallbackReturn.FAILURE
    finally:
        node.destroy_node()


def test_set_port_service_turns_port_on():
    node, hub = _make_node()
    try:
        node.on_configure(None)
        resp = node._on_set_port(SetBool.Request(data=True), SetBool.Response(), port=2)
        assert resp.success is True
        assert hub.states[1] is True
    finally:
        node.destroy_node()


def test_set_port_service_off():
    node, hub = _make_node(hub=FakeHubSerial(states=[True, True, True, True]))
    try:
        node.on_configure(None)
        resp = node._on_set_port(SetBool.Request(data=False), SetBool.Response(), port=3)
        assert resp.success is True
        assert hub.states[2] is False
    finally:
        node.destroy_node()


def test_protected_port_service_refused():
    hub = FakeHubSerial(states=[True, True, True, True])
    node, _ = _make_node(hub=hub, protected_ports=[1])
    try:
        node.on_configure(None)
        resp = node._on_set_port(SetBool.Request(data=False), SetBool.Response(), port=1)
        assert resp.success is False
        assert "안전" in resp.message
        assert hub.states[0] is True  # 차단 안 됨
    finally:
        node.destroy_node()


def test_reset_and_save_triggers():
    node, hub = _make_node()
    try:
        node.on_configure(None)
        assert node._on_reset(Trigger.Request(), Trigger.Response()).success is True
        assert node._on_save(Trigger.Request(), Trigger.Response()).success is True
        fr = node._on_factory_reset(Trigger.Request(), Trigger.Response())
        assert fr.success is True
    finally:
        node.destroy_node()


def test_activate_starts_polling_timer():
    node, hub = _make_node()
    try:
        node.on_configure(None)
        assert node.on_activate(None) == TransitionCallbackReturn.SUCCESS
        assert node._poll_timer is not None
        node.on_deactivate(None)
        assert node._poll_timer is None
    finally:
        node.destroy_node()
