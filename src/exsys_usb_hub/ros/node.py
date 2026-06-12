"""ExsysHubNode — 코어 HubManager 를 감싸는 ROS2 Lifecycle 노드.

인터페이스
----------
서비스
    ``~/port_<N>/set``  (std_srvs/SetBool)  : 포트 N 을 ON(true)/OFF(false)
    ``~/reset``         (std_srvs/Trigger)  : 허브 리셋
    ``~/factory_reset`` (std_srvs/Trigger)  : 공장 초기화
    ``~/save``          (std_srvs/Trigger)  : 현재 상태를 전원-기본값으로 저장
토픽
    ``~/port_states``   (std_msgs/Int32MultiArray, latched) : 포트별 0/1
    ``/diagnostics``    (diagnostic_msgs/DiagnosticArray)   : 연결·포트 상태

파라미터
--------
``device_path``, ``baudrate``, ``timeout``, ``poll_rate_hz``,
``protected_ports``, ``inrush_delay_ms``, ``verify_retries``, ``port_names``.

설계 메모
---------
시리얼 I/O 는 블로킹이지만, 서비스 콜백과 폴링 타이머를 ReentrantCallbackGroup
에 두고 :func:`main` 에서 MultiThreadedExecutor 로 돌리면 서로 막지 않는다.
실제 시리얼 접근은 코어의 ``transport.lock`` 이 직렬화하므로 안전하다.
"""

from __future__ import annotations

import functools

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rcl_interfaces.msg import ParameterDescriptor, ParameterType
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.lifecycle import Node, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Int32MultiArray
from std_srvs.srv import SetBool, Trigger

from ..core import (
    HubError,
    HubManager,
    SafetyViolation,
    SerialTransport,
)

_INT_ARRAY = ParameterDescriptor(type=ParameterType.PARAMETER_INTEGER_ARRAY)
_STR_ARRAY = ParameterDescriptor(type=ParameterType.PARAMETER_STRING_ARRAY)

# port_states 는 늦게 구독한 노드도 마지막 값을 받도록 latched.
_LATCHED_QOS = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)


class ExsysHubNode(Node):
    """Exsys USB 허브 Lifecycle 노드.

    Parameters
    ----------
    manager_factory:
        ``() -> HubManager`` 콜러블. 테스트에서 FakeHubSerial 기반 매니저를
        주입할 때 사용한다. 없으면 파라미터로부터 구성한다.
    """

    def __init__(self, manager_factory=None, **kwargs) -> None:
        super().__init__("exsys_hub_node", **kwargs)
        self._manager_factory = manager_factory
        self._manager: HubManager | None = None
        self._cb = ReentrantCallbackGroup()
        self._set_srvs: list = []
        self._reset_srv = self._factory_srv = self._save_srv = None
        self._states_pub = self._diag_pub = None
        self._poll_timer = None

        self.declare_parameter("device_path", "/dev/exsys_hub")
        self.declare_parameter("baudrate", 9600)
        self.declare_parameter("timeout", 2.0)
        self.declare_parameter("poll_rate_hz", 1.0)
        self.declare_parameter("protected_ports", [], _INT_ARRAY)
        self.declare_parameter("inrush_delay_ms", 500)
        self.declare_parameter("verify_retries", 2)
        self.declare_parameter("port_names", [], _STR_ARRAY)

    # ------------------------------------------------------------------
    # Lifecycle 전이
    # ------------------------------------------------------------------

    def on_configure(self, state) -> TransitionCallbackReturn:
        """매니저를 구성·연결하고 서비스/퍼블리셔를 만든다."""
        try:
            self._manager = (
                self._manager_factory() if self._manager_factory
                else self._build_manager()
            )
            self._manager.connect()
        except HubError as exc:
            self.get_logger().error(f"허브 연결 실패: {exc}")
            self._manager = None
            return TransitionCallbackReturn.FAILURE

        n = self._manager.n_ports
        self.get_logger().info(
            f"연결됨: {self._manager.info().model} ({n} 포트, "
            f"fw {self._manager.info().firmware})"
        )

        # 포트별 SetBool 서비스
        self._set_srvs = [
            self.create_service(
                SetBool, f"~/port_{i}/set",
                functools.partial(self._on_set_port, port=i),
                callback_group=self._cb,
            )
            for i in range(1, n + 1)
        ]
        self._reset_srv = self.create_service(
            Trigger, "~/reset", self._on_reset, callback_group=self._cb)
        self._factory_srv = self.create_service(
            Trigger, "~/factory_reset", self._on_factory_reset, callback_group=self._cb)
        self._save_srv = self.create_service(
            Trigger, "~/save", self._on_save, callback_group=self._cb)

        self._states_pub = self.create_lifecycle_publisher(
            Int32MultiArray, "~/port_states", _LATCHED_QOS)
        self._diag_pub = self.create_lifecycle_publisher(
            DiagnosticArray, "/diagnostics", 10)
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state) -> TransitionCallbackReturn:
        """폴링 타이머를 시작한다."""
        hz = self.get_parameter("poll_rate_hz").value or 1.0
        self._poll_timer = self.create_timer(
            1.0 / hz, self._publish_all, callback_group=self._cb)
        self._publish_all()
        return super().on_activate(state)

    def on_deactivate(self, state) -> TransitionCallbackReturn:
        if self._poll_timer is not None:
            self.destroy_timer(self._poll_timer)
            self._poll_timer = None
        return super().on_deactivate(state)

    def on_cleanup(self, state) -> TransitionCallbackReturn:
        self._teardown()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state) -> TransitionCallbackReturn:
        self._teardown()
        return TransitionCallbackReturn.SUCCESS

    # ------------------------------------------------------------------
    # 서비스 콜백
    # ------------------------------------------------------------------

    def _on_set_port(self, request, response, port: int):
        try:
            self._manager.set_port(port, request.data)
            response.success = True
            response.message = f"포트 {port} -> {'ON' if request.data else 'OFF'}"
        except SafetyViolation as exc:
            response.success = False
            response.message = f"안전 정책 거부: {exc}"
            self.get_logger().warn(response.message)
        except (HubError, ValueError) as exc:
            response.success = False
            response.message = str(exc)
            self.get_logger().error(f"포트 {port} 설정 실패: {exc}")
        self._publish_all()
        return response

    def _on_reset(self, request, response):
        return self._run_trigger(response, self._manager.reset, "reset")

    def _on_factory_reset(self, request, response):
        return self._run_trigger(response, self._manager.factory_reset, "factory_reset")

    def _on_save(self, request, response):
        return self._run_trigger(response, self._manager.save, "save")

    def _run_trigger(self, response, fn, label: str):
        try:
            fn()
            response.success = True
            response.message = f"{label}: OK"
        except HubError as exc:
            response.success = False
            response.message = f"{label} 실패: {exc}"
            self.get_logger().error(response.message)
        self._publish_all()
        return response

    # ------------------------------------------------------------------
    # 발행
    # ------------------------------------------------------------------

    def _publish_all(self) -> None:
        states, connected, err = None, True, ""
        try:
            states = self._manager.status()
        except HubError as exc:
            connected, err = False, str(exc)

        if states is not None and self._states_pub is not None:
            self._states_pub.publish(Int32MultiArray(data=[int(s) for s in states]))
        self._publish_diagnostics(connected, states, err)

    def _publish_diagnostics(self, connected: bool, states, err: str) -> None:
        if self._diag_pub is None:
            return
        st = DiagnosticStatus()
        st.name = f"{self.get_name()}: hub"
        st.hardware_id = self.get_parameter("device_path").value
        if connected:
            st.level = DiagnosticStatus.OK
            st.message = "connected"
            st.values.append(KeyValue(key="firmware", value=self._manager.info().firmware))
        else:
            st.level = DiagnosticStatus.ERROR
            st.message = err or "disconnected"
        if states is not None:
            for i, s in enumerate(states, start=1):
                st.values.append(KeyValue(key=self._port_label(i), value="ON" if s else "OFF"))
        arr = DiagnosticArray()
        arr.header.stamp = self.get_clock().now().to_msg()
        arr.status = [st]
        self._diag_pub.publish(arr)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _build_manager(self) -> HubManager:
        transport = SerialTransport(
            self.get_parameter("device_path").value,
            baudrate=int(self.get_parameter("baudrate").value),
            timeout=float(self.get_parameter("timeout").value),
        )
        return HubManager(
            transport,
            protected_ports=list(self.get_parameter("protected_ports").value or []),
            inrush_delay_s=int(self.get_parameter("inrush_delay_ms").value) / 1000.0,
            verify_retries=int(self.get_parameter("verify_retries").value),
            name=self.get_name(),
        )

    def _port_label(self, port: int) -> str:
        names = list(self.get_parameter("port_names").value or [])
        if port <= len(names) and names[port - 1]:
            return f"{names[port - 1]} (Port {port})"
        return f"Port {port}"

    def _teardown(self) -> None:
        for srv in (*self._set_srvs, self._reset_srv, self._factory_srv, self._save_srv):
            if srv is not None:
                self.destroy_service(srv)
        self._set_srvs = []
        self._reset_srv = self._factory_srv = self._save_srv = None
        if self._poll_timer is not None:
            self.destroy_timer(self._poll_timer)
            self._poll_timer = None
        if self._manager is not None:
            self._manager.close()
            self._manager = None


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ExsysHubNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
