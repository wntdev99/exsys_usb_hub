"""ExsysHubNode 검증 — 단일 노드 다중 허브 + 이름 기반 라우팅.

rclpy + exsys_usb_hub_msgs 가 필요하다(없으면 skip). FakeHubSerial 기반 허브를
주입해 하드웨어 없이 노드 로직을 검증한다. 전이 콜백을 직접 호출하므로 executor
스핀 없이 동작을 확인할 수 있다.
"""

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("exsys_usb_hub_msgs")

from rclpy.lifecycle import TransitionCallbackReturn  # noqa: E402
from std_srvs.srv import Trigger  # noqa: E402

from exsys_usb_hub_msgs.srv import SetPort  # noqa: E402

from exsys_usb_hub.core import HubManager, SerialTransport  # noqa: E402
from exsys_usb_hub.ros.node import ExsysHubNode  # noqa: E402

from fakes import FakeHubSerial  # noqa: E402


@pytest.fixture(autouse=True)
def _rclpy():
    rclpy.init()
    yield
    rclpy.shutdown()


def _mgr(hub, protected=()):
    transport = SerialTransport(
        "/dev/fake", serial_factory=lambda port, **kw: hub, sleep=lambda d: None
    )
    return HubManager(transport, protected_ports=protected, sleep=lambda d: None)


def _two_hub_node(names_a=("cam_a", "cam_b", "", ""),
                  names_b=("cam_c", "cam_d", "lidar", ""),
                  protected_a=()):
    hub_a = FakeHubSerial(states=[True, False, False, False])
    hub_b = FakeHubSerial(states=[False, False, False, False])

    def factory():
        return [
            ("hub_a", _mgr(hub_a, protected_a), list(names_a)),
            ("hub_b", _mgr(hub_b), list(names_b)),
        ]

    return ExsysHubNode(hubs_factory=factory), hub_a, hub_b


# ---------------------------------------------------------------------------
# configure / 이름 인덱스
# ---------------------------------------------------------------------------
def test_configure_builds_name_index():
    node, _, _ = _two_hub_node()
    try:
        assert node.on_configure(None) == TransitionCallbackReturn.SUCCESS
        assert node._set_srv is not None
        # 비어있지 않은 이름 5개만 라우팅 대상
        assert set(node._name_index) == {"cam_a", "cam_b", "cam_c", "cam_d", "lidar"}
        assert node._name_index["cam_c"] == ("hub_b", 1)
    finally:
        node.destroy_node()


def test_duplicate_names_fail_configure():
    # 두 허브에 "cam_a" 가 중복 → 전역 고유 위반
    node, _, _ = _two_hub_node(names_b=("cam_a", "cam_d", "lidar", ""))
    try:
        assert node.on_configure(None) == TransitionCallbackReturn.FAILURE
    finally:
        node.destroy_node()


# ---------------------------------------------------------------------------
# 이름 기반 set_port 라우팅
# ---------------------------------------------------------------------------
def test_set_port_routes_to_correct_hub():
    node, hub_a, hub_b = _two_hub_node()
    try:
        node.on_configure(None)
        # cam_a 는 hub_a 포트1 (현재 ON) → OFF
        r1 = node._on_set_port(SetPort.Request(port="cam_a", state=False), SetPort.Response())
        assert r1.success is True
        assert hub_a.states[0] is False
        # cam_c 는 hub_b 포트1 → ON
        r2 = node._on_set_port(SetPort.Request(port="cam_c", state=True), SetPort.Response())
        assert r2.success is True
        assert hub_b.states[0] is True
    finally:
        node.destroy_node()


def test_set_port_unknown_name():
    node, _, _ = _two_hub_node()
    try:
        node.on_configure(None)
        r = node._on_set_port(SetPort.Request(port="nope", state=True), SetPort.Response())
        assert r.success is False
        assert "알 수 없는" in r.message
    finally:
        node.destroy_node()


def test_set_port_never_raises_on_unexpected_error():
    """매니저가 예상 못 한 예외를 던져도 서비스는 success=false 만 반환한다."""
    class _BoomManager:
        def connect(self):
            pass

        def info(self):
            raise RuntimeError("boom")

        def set_port(self, idx, state):
            raise RuntimeError("unexpected")

        def status(self):
            raise RuntimeError("boom")

        def close(self):
            pass

    node = ExsysHubNode(hubs_factory=lambda: [("hub_x", _BoomManager(), ["cam_x", "", "", ""])])
    try:
        node.on_configure(None)
        r = node._on_set_port(SetPort.Request(port="cam_x", state=True), SetPort.Response())
        assert r.success is False
        assert "실패" in r.message
    finally:
        node.destroy_node()


def test_protected_port_refused_by_name():
    node, hub_a, _ = _two_hub_node(protected_a=[1])  # hub_a 포트1 = cam_a 보호
    try:
        node.on_configure(None)
        r = node._on_set_port(SetPort.Request(port="cam_a", state=False), SetPort.Response())
        assert r.success is False
        assert "안전" in r.message
        assert hub_a.states[0] is True  # 차단 안 됨
    finally:
        node.destroy_node()


# ---------------------------------------------------------------------------
# 전체 허브 명령
# ---------------------------------------------------------------------------
def test_reset_and_save_all_hubs():
    node, _, _ = _two_hub_node()
    try:
        node.on_configure(None)
        r = node._on_reset(Trigger.Request(), Trigger.Response())
        assert r.success is True
        assert "hub_a:OK" in r.message and "hub_b:OK" in r.message
        assert node._on_save(Trigger.Request(), Trigger.Response()).success is True
    finally:
        node.destroy_node()


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def test_activate_starts_polling_timer():
    node, _, _ = _two_hub_node()
    try:
        node.on_configure(None)
        assert node.on_activate(None) == TransitionCallbackReturn.SUCCESS
        assert node._poll_timer is not None
        node.on_deactivate(None)
        assert node._poll_timer is None
    finally:
        node.destroy_node()


# ---------------------------------------------------------------------------
# 배열 파라미터 회귀 (빈 기본값 + 오버라이드)
# ---------------------------------------------------------------------------
def test_array_params_accept_overrides():
    from rclpy.parameter import Parameter
    node = ExsysHubNode(parameter_overrides=[
        Parameter("protected_ports", value=[1, 3]),
        Parameter("port_names", value=["A", "B", "C", "D"]),
    ])
    try:
        assert list(node.get_parameter("protected_ports").value) == [1, 3]
        assert list(node.get_parameter("port_names").value) == ["A", "B", "C", "D"]
    finally:
        node.destroy_node()


def test_array_params_default_empty():
    node = ExsysHubNode()
    try:
        assert list(node.get_parameter("protected_ports").value) == []
    finally:
        node.destroy_node()
