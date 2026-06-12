"""코어 예외 계층 — ROS 비의존.

모든 코어 예외는 :class:`HubError` 를 상속하므로, 호출자는
``except HubError`` 한 줄로 모든 허브 관련 오류를 잡을 수 있다.
"""

from __future__ import annotations


class HubError(Exception):
    """모든 허브 관련 오류의 최상위 타입."""


class HubConnectionError(HubError):
    """시리얼 포트를 열 수 없거나 연결이 끊긴 경우."""


class HubTimeoutError(HubError):
    """허브가 제한 시간 내에 응답하지 않는 경우."""


class HubResponseError(HubError):
    """허브가 예상치 못한 응답을 반환한 경우 (명령 거부 등)."""


class ProtocolError(HubError):
    """와이어 데이터가 프로토콜 규격에 맞지 않아 인코딩/디코딩이 불가능한 경우.

    I/O 없이 순수 코덱 단계에서만 발생한다 (:mod:`exsys_usb_hub.core.protocol`).
    """
