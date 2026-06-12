"""ExsysHubNode — 여러 Exsys 허브를 관리하는 단일 ROS2 Lifecycle 노드.

설계 요지
---------
노드 하나가 N개의 :class:`HubManager` 를 들고, **포트 이름**(전역 고유)으로
허브를 자동 라우팅한다. 외부에서는 허브 위치를 몰라도 포트 이름만으로 제어한다.

인터페이스
----------
서비스
    ``~/set_port``      (exsys_usb_hub_msgs/SetPort)  : 포트 이름으로 ON/OFF
    ``~/reset``         (std_srvs/Trigger)            : 전체 허브 리셋
    ``~/factory_reset`` (std_srvs/Trigger)            : 전체 허브 공장 초기화
    ``~/save``          (std_srvs/Trigger)            : 전체 허브 상태 저장
토픽
    ``~/hub_status``    (exsys_usb_hub_msgs/HubStatus, latched) : 전 포트 상태(이름 포함)
    ``/diagnostics``    (diagnostic_msgs/DiagnosticArray)        : 허브별 연결/포트 상태

파라미터
--------
``config_file``  : 허브 목록 YAML 경로 (있으면 우선). 형식은 config/exsys_hub_multi.yaml.
없으면 단일 허브를 스칼라 파라미터로 구성:
``device_path``, ``baudrate``, ``timeout``, ``poll_rate_hz``,
``protected_ports``, ``inrush_delay_ms``, ``verify_retries``, ``port_names``.

포트 이름은 **전역 고유**여야 한다. 중복(비어있지 않은) 이름이 있으면 configure 가
실패한다. 빈 이름("")은 라우팅 대상에서 제외된다(미사용 포트).
"""

from __future__ import annotations

import yaml
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.lifecycle import Node, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_srvs.srv import Trigger

import rclpy
from exsys_usb_hub_msgs.msg import HubStatus, PortState
from exsys_usb_hub_msgs.srv import SetPort

from ..core import HubError, HubManager, SafetyViolation, SerialTransport

# 배열 파라미터는 동적 타이핑으로 선언(빈 기본값[]의 타입 추론 충돌 방지).
_ARRAY_PARAM = ParameterDescriptor(dynamic_typing=True)

# 늦게 구독해도 마지막 값을 받도록 latched.
_LATCHED_QOS = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)


class _Hub:
    """노드가 들고 있는 단일 허브 핸들."""

    def __init__(self, name: str, manager: HubManager, port_names: list[str]) -> None:
        self.name = name
        self.manager = manager
        self.port_names = port_names
        self.connected = False


class ExsysHubNode(Node):
    """여러 허브를 관리하는 단일 Lifecycle 노드.

    Parameters
    ----------
    hubs_factory:
        ``() -> list[tuple[str, HubManager, list[str]]]`` 콜러블. 테스트에서
        FakeHubSerial 기반 허브들을 주입할 때 사용한다. 없으면 파라미터로 구성.
    """

    def __init__(self, hubs_factory=None, **kwargs) -> None:
        super().__init__("exsys_hub_node", **kwargs)
        self._hubs_factory = hubs_factory
        self._cb = ReentrantCallbackGroup()
        self._hubs: dict[str, _Hub] = {}
        self._name_index: dict[str, tuple[str, int]] = {}  # 포트이름 -> (허브, 1-indexed)
        self._set_srv = self._reset_srv = self._factory_srv = self._save_srv = None
        self._status_pub = self._diag_pub = None
        self._poll_timer = None

        self.declare_parameter("config_file", "")
        self.declare_parameter("device_path", "/dev/exsys_hub")
        self.declare_parameter("baudrate", 9600)
        self.declare_parameter("timeout", 2.0)
        self.declare_parameter("poll_rate_hz", 1.0)
        self.declare_parameter("protected_ports", [], _ARRAY_PARAM)
        self.declare_parameter("inrush_delay_ms", 500)
        self.declare_parameter("verify_retries", 2)
        self.declare_parameter("port_names", [], _ARRAY_PARAM)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_configure(self, state) -> TransitionCallbackReturn:
        try:
            entries = self._make_hubs()
        except Exception as exc:  # noqa: BLE001 — 설정 오류는 FAILURE 로 보고
            self.get_logger().error(f"허브 구성 실패: {exc}")
            return TransitionCallbackReturn.FAILURE

        # 전역 이름 인덱스 구성 + 고유성 검증
        self._hubs.clear()
        self._name_index.clear()
        dupes = set()
        for name, manager, port_names in entries:
            hub = _Hub(name, manager, list(port_names))
            self._hubs[name] = hub
            for idx, pname in enumerate(hub.port_names, start=1):
                if not pname:
                    continue
                if pname in self._name_index:
                    dupes.add(pname)
                else:
                    self._name_index[pname] = (name, idx)
        if dupes:
            self.get_logger().error(
                f"중복된 포트 이름(전역 고유 위반): {sorted(dupes)}. "
                "각 포트 이름은 모든 허브에서 유일해야 합니다."
            )
            return TransitionCallbackReturn.FAILURE

        # best-effort 연결: 일부 실패해도 나머지는 살린다(트랜스포트가 추후 재연결).
        for hub in self._hubs.values():
            try:
                hub.manager.connect()
                info = hub.manager.info()
                hub.connected = True
                self.get_logger().info(
                    f"[{hub.name}] 연결됨: {info.model} ({info.n_ports}포트, fw {info.firmware})"
                )
            except Exception as exc:  # noqa: BLE001 — 한 허브 실패가 configure 를 막지 않는다
                hub.connected = False
                self.get_logger().warn(f"[{hub.name}] 연결 실패(추후 재시도): {exc}")

        self._set_srv = self.create_service(
            SetPort, "~/set_port", self._on_set_port, callback_group=self._cb)
        self._reset_srv = self.create_service(
            Trigger, "~/reset", self._on_reset, callback_group=self._cb)
        self._factory_srv = self.create_service(
            Trigger, "~/factory_reset", self._on_factory_reset, callback_group=self._cb)
        self._save_srv = self.create_service(
            Trigger, "~/save", self._on_save, callback_group=self._cb)

        self._status_pub = self.create_lifecycle_publisher(
            HubStatus, "~/hub_status", _LATCHED_QOS)
        self._diag_pub = self.create_lifecycle_publisher(
            DiagnosticArray, "/diagnostics", 10)

        self.get_logger().info(
            f"{len(self._hubs)}개 허브 구성 완료, 제어 가능한 포트 이름 {len(self._name_index)}개."
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state) -> TransitionCallbackReturn:
        hz = self.get_parameter("poll_rate_hz").value or 1.0
        self._poll_timer = self.create_timer(
            1.0 / hz, self._safe_publish, callback_group=self._cb)
        self._safe_publish()
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

    def _on_set_port(self, request, response):
        # 서비스 핸들러는 어떤 입력/오류에도 예외를 던지지 않고 항상 응답을 채운다.
        try:
            entry = self._name_index.get(request.port)
            if entry is None:
                response.success = False
                response.message = (
                    f"알 수 없는 포트 이름 '{request.port}'. "
                    f"사용 가능: {sorted(self._name_index)}"
                )
            else:
                hub_name, idx = entry
                self._hubs[hub_name].manager.set_port(idx, request.state)
                response.success = True
                response.message = (
                    f"{request.port} ({hub_name}:{idx}) -> "
                    f"{'ON' if request.state else 'OFF'}"
                )
        except SafetyViolation as exc:
            response.success = False
            response.message = f"안전 정책 거부: {exc}"
            self.get_logger().warn(response.message)
        except Exception as exc:  # noqa: BLE001 — 서비스는 절대 죽지 않는다
            response.success = False
            response.message = f"설정 실패: {exc}"
            self.get_logger().error(f"set_port 실패 ('{request.port}'): {exc}")
        self._safe_publish()
        return response

    def _on_reset(self, request, response):
        return self._run_all(response, lambda m: m.reset(), "reset")

    def _on_factory_reset(self, request, response):
        return self._run_all(response, lambda m: m.factory_reset(), "factory_reset")

    def _on_save(self, request, response):
        return self._run_all(response, lambda m: m.save(), "save")

    def _run_all(self, response, fn, label: str):
        """모든 허브에 동작을 수행하고 허브별 결과를 보고한다. 예외를 던지지 않는다."""
        results = []
        ok = True
        for name, hub in self._hubs.items():
            try:
                fn(hub.manager)
                results.append(f"{name}:OK")
            except Exception as exc:  # noqa: BLE001 — 한 허브 실패가 서비스를 죽이지 않는다
                ok = False
                results.append(f"{name}:FAIL({exc})")
        response.success = ok
        response.message = f"{label} — " + ", ".join(results) if results else f"{label} — (허브 없음)"
        self._safe_publish()
        return response

    # ------------------------------------------------------------------
    # 발행
    # ------------------------------------------------------------------

    def _safe_publish(self) -> None:
        """상태 발행을 시도하되, 실패가 서비스 콜백을 죽이지 않도록 감싼다."""
        try:
            self._publish_all()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"상태 발행 실패: {exc}")

    def _publish_all(self) -> None:
        msg = HubStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        diag = []
        for name, hub in self._hubs.items():
            try:
                states = hub.manager.status()
                hub.connected = True
            except Exception as exc:  # noqa: BLE001 — 한 허브 오류가 다른 허브 발행을 막지 않는다
                hub.connected = False
                diag.append(self._diag(name, hub, False, str(exc), None))
                continue
            for idx, on in enumerate(states, start=1):
                ps = PortState()
                ps.hub = name
                ps.index = idx
                ps.name = hub.port_names[idx - 1] if idx - 1 < len(hub.port_names) else ""
                ps.on = on
                msg.ports.append(ps)
            diag.append(self._diag(name, hub, True, "", states))

        if self._status_pub is not None:
            self._status_pub.publish(msg)
        if self._diag_pub is not None:
            arr = DiagnosticArray()
            arr.header.stamp = self.get_clock().now().to_msg()
            arr.status = diag
            self._diag_pub.publish(arr)

    def _diag(self, name: str, hub: _Hub, connected: bool, err: str, states):
        st = DiagnosticStatus()
        st.name = f"{self.get_name()}: {name}"
        st.hardware_id = name
        if connected:
            st.level = DiagnosticStatus.OK
            st.message = "connected"
            try:
                st.values.append(KeyValue(key="firmware", value=hub.manager.info().firmware))
            except Exception:  # noqa: BLE001
                pass
            if states is not None:
                for idx, on in enumerate(states, start=1):
                    label = hub.port_names[idx - 1] if idx - 1 < len(hub.port_names) else ""
                    st.values.append(KeyValue(key=label or f"port_{idx}",
                                              value="ON" if on else "OFF"))
        else:
            st.level = DiagnosticStatus.ERROR
            st.message = err or "disconnected"
        return st

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _make_hubs(self):
        """(name, HubManager, port_names) 리스트를 만든다."""
        if self._hubs_factory:
            return self._hubs_factory()
        return [
            (spec["name"], self._build_manager_from_spec(spec),
             list(spec.get("port_names", [])))
            for spec in self._load_specs()
        ]

    def _load_specs(self) -> list[dict]:
        config_file = self.get_parameter("config_file").value
        if config_file:
            with open(config_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            specs = data.get("hubs", [])
            if not specs:
                raise RuntimeError(f"config_file 에 'hubs' 항목이 없습니다: {config_file}")
            return specs
        # 단일 허브 fallback (스칼라 파라미터)
        return [{
            "name": "hub",
            "device_path": self.get_parameter("device_path").value,
            "baudrate": int(self.get_parameter("baudrate").value),
            "timeout": float(self.get_parameter("timeout").value),
            "protected_ports": list(self.get_parameter("protected_ports").value or []),
            "inrush_delay_ms": int(self.get_parameter("inrush_delay_ms").value),
            "verify_retries": int(self.get_parameter("verify_retries").value),
            "port_names": list(self.get_parameter("port_names").value or []),
        }]

    def _build_manager_from_spec(self, spec: dict) -> HubManager:
        transport = SerialTransport(
            spec["device_path"],
            baudrate=int(spec.get("baudrate", 9600)),
            timeout=float(spec.get("timeout", 2.0)),
        )
        return HubManager(
            transport,
            protected_ports=list(spec.get("protected_ports", []) or []),
            inrush_delay_s=int(spec.get("inrush_delay_ms", 500)) / 1000.0,
            verify_retries=int(spec.get("verify_retries", 2)),
            name=spec["name"],
        )

    def _teardown(self) -> None:
        for srv in (self._set_srv, self._reset_srv, self._factory_srv, self._save_srv):
            if srv is not None:
                self.destroy_service(srv)
        self._set_srv = self._reset_srv = self._factory_srv = self._save_srv = None
        if self._poll_timer is not None:
            self.destroy_timer(self._poll_timer)
            self._poll_timer = None
        for hub in self._hubs.values():
            hub.manager.close()
        self._hubs.clear()
        self._name_index.clear()


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
