"""ROS 비의존 코어 — 프로토콜·시리얼·안전정책.

이 하위 패키지는 rclpy 를 import 하지 않으므로 ROS 환경 없이도 동작한다.
"""

from .errors import (
    HubConnectionError,
    HubError,
    HubResponseError,
    HubTimeoutError,
    ProtocolError,
    SafetyViolation,
)
from .manager import HubManager
from .protocol import HubInfo
from .transport import SerialTransport

__all__ = [
    "HubManager",
    "SerialTransport",
    "HubInfo",
    "HubError",
    "HubConnectionError",
    "HubTimeoutError",
    "HubResponseError",
    "ProtocolError",
    "SafetyViolation",
]
