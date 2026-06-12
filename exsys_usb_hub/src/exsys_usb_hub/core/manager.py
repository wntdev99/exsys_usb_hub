"""HubManager — 고수준 허브 제어 + 안전 정책.

코덱(:mod:`.protocol`)과 트랜스포트(:mod:`.transport`)를 조합해
``on``/``off``/``status``/``info`` 같은 의미 있는 API 를 제공한다. ROS 의존성은
전혀 없으므로 노트북/CLI/테스트에서 그대로 쓸 수 있고, ROS2 노드는 이 위에 얇게
얹힌다.

안전 정책
---------
- **보호 포트(protected_ports)** : 메인 컴퓨트나 허브 자기 자신이 물린 포트를
  실수로 차단하지 못하도록 OFF 요청을 거부한다.
- **인러시 지연(inrush_delay)** : 포트를 OFF 한 직후 곧바로 ON 하면 돌입 전류가
  튀거나 장치가 완전히 리셋되지 않을 수 있다. OFF→ON 사이 최소 시간을 강제한다.
- **set 후 read-back 검증** : 명령 ACK 만 믿지 않고 실제 포트 상태를 다시 읽어
  목표와 일치하는지 확인하며, 불일치 시 재시도한다.

read-modify-write 원자성
------------------------
포트 1개를 바꾸려면 전체 상태를 읽고→1비트 수정→전체를 다시 쓴다. 이 과정을
``transport.lock`` 으로 묶어, 두 스레드가 서로 다른 포트를 동시에 건드려도 한쪽이
상대의 변경을 덮어쓰지 않게 한다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Callable

from . import protocol
from .errors import HubConnectionError, HubResponseError, SafetyViolation
from .protocol import HubInfo
from .transport import SerialTransport


class HubManager:
    """단일 Exsys 허브의 고수준 제어기.

    다중 허브는 시리얼 번호별로 ``HubManager`` 인스턴스를 여러 개 두어 처리한다
    (각 인스턴스가 자기 트랜스포트를 소유). ``name`` 으로 식별한다.

    Parameters
    ----------
    transport:
        연결을 담당하는 :class:`SerialTransport`.
    protected_ports:
        OFF 를 거부할 포트 번호들(1-indexed).
    inrush_delay_s:
        같은 포트의 OFF→ON 사이 최소 대기(초).
    verify_retries:
        set 후 read-back 불일치 시 재시도 횟수.
    name:
        다중 허브 식별용 라벨.
    """

    def __init__(
        self,
        transport: SerialTransport,
        *,
        protected_ports: Iterable[int] = (),
        inrush_delay_s: float = 0.0,
        verify_retries: int = 2,
        name: str = "exsys_hub",
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        self._transport = transport
        self._protected_ports = frozenset(protected_ports)
        self._inrush_delay = inrush_delay_s
        self._verify_retries = verify_retries
        self.name = name
        self._monotonic = monotonic
        self._sleep = sleep
        self._log = logger or logging.getLogger(__name__)

        self._info: HubInfo | None = None
        self._last_off: dict[int, float] = {}

    # ------------------------------------------------------------------
    # 수명주기
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """연결하고 장치 정보를 조회·캐시한다."""
        self._transport.connect()
        resp = self._transport.transaction(protocol.CMD_QUERY_INFO)
        self._info = protocol.parse_info_response(resp)

    def close(self) -> None:
        self._transport.close()

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    def __enter__(self) -> "HubManager":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def info(self) -> HubInfo:
        """캐시된 장치 메타데이터를 반환한다."""
        self._require_info()
        assert self._info is not None
        return self._info

    @property
    def n_ports(self) -> int:
        self._require_info()
        assert self._info is not None
        return self._info.n_ports

    def status(self) -> list[bool]:
        """전체 포트 상태(1-indexed: result[0] == 포트 1)를 반환한다."""
        return self._read_states()

    def get_port(self, port: int) -> bool:
        """단일 포트 상태를 반환한다(1-indexed)."""
        self._validate_port(port)
        return self._read_states()[port - 1]

    # ------------------------------------------------------------------
    # 제어
    # ------------------------------------------------------------------

    def on(self, port: int) -> bool:
        """포트를 ON 한다."""
        return self.set_port(port, True)

    def off(self, port: int) -> bool:
        """포트를 OFF 한다 (보호 포트는 거부)."""
        return self.set_port(port, False)

    def set_port(self, port: int, state: bool) -> bool:
        """포트 상태를 설정한다 — 안전 정책·인러시·read-back 검증 포함.

        Raises
        ------
        SafetyViolation
            보호 포트를 OFF 하려는 경우.
        HubResponseError
            허브가 명령을 거부하거나 read-back 검증이 끝내 실패한 경우.
        """
        self._validate_port(port)
        if not state and port in self._protected_ports:
            raise SafetyViolation(
                f"포트 {port} 는 보호 포트(protected_ports)라 차단할 수 없습니다."
            )

        # read-modify-write 전체를 락으로 묶어 원자적으로 처리.
        with self._transport.lock:
            if state:
                self._enforce_inrush(port)
            self._apply_and_verify(port, state)
            if not state:
                self._last_off[port] = self._monotonic()
        return True

    def power_cycle(self, port: int) -> bool:
        """포트를 OFF → (인러시 지연) → ON 한다."""
        self.off(port)
        return self.on(port)

    def reset(self) -> None:
        """허브를 리셋한다."""
        self._require_connected()
        self._transport.transaction(protocol.CMD_RESET)

    def factory_reset(self) -> list[bool]:
        """공장 초기화 후 포트 상태를 반환한다."""
        self._require_connected()
        resp = self._transport.transaction(protocol.CMD_FACTORY_RESET)
        if not protocol.is_ack(resp):
            raise HubResponseError(f"허브가 공장 초기화를 거부: {resp!r}")
        return self._read_states()

    def save(self) -> None:
        """현재 상태를 전원-기본값으로 저장한다."""
        self._require_connected()
        resp = self._transport.transaction(protocol.CMD_SAVE)
        if not protocol.is_ack(resp):
            raise HubResponseError(f"허브가 저장 명령을 거부: {resp!r}")

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if not self._transport.is_connected:
            raise HubConnectionError("연결되지 않았습니다. connect() 를 먼저 호출하세요.")

    def _require_info(self) -> None:
        if self._info is None:
            raise HubConnectionError("장치 정보가 없습니다. connect() 를 먼저 호출하세요.")

    def _validate_port(self, port: int) -> None:
        self._require_info()
        assert self._info is not None
        if not (1 <= port <= self._info.n_ports):
            raise ValueError(
                f"포트 {port} 범위 초과. 이 허브는 {self._info.n_ports}포트입니다 "
                f"(1–{self._info.n_ports})."
            )

    def _read_states(self) -> list[bool]:
        self._require_info()
        assert self._info is not None
        resp = self._transport.transaction(protocol.CMD_GET_STATES)
        return protocol.decode_port_states(resp, self._info.n_ports)

    def _enforce_inrush(self, port: int) -> None:
        """OFF→ON 시 최소 OFF 시간을 보장한다."""
        if self._inrush_delay <= 0:
            return
        last_off = self._last_off.get(port)
        if last_off is None:
            return
        elapsed = self._monotonic() - last_off
        remaining = self._inrush_delay - elapsed
        if remaining > 0:
            self._log.debug("포트 %d 인러시 지연 %.3fs 대기", port, remaining)
            self._sleep(remaining)

    def _apply_and_verify(self, port: int, state: bool) -> None:
        """포트 설정을 적용하고 read-back 으로 검증한다 (불일치 시 재시도)."""
        assert self._info is not None
        n = self._info.n_ports
        for attempt in range(self._verify_retries + 1):
            states = self._read_states()
            states[port - 1] = state
            resp = self._transport.transaction(protocol.build_set_command(states, n))
            if not protocol.is_ack(resp):
                raise HubResponseError(f"허브가 포트 설정을 거부: {resp!r}")
            if self._read_states()[port - 1] == state:
                return
            self._log.warning(
                "포트 %d 설정 검증 실패, 재시도 %d/%d",
                port, attempt + 1, self._verify_retries,
            )
        raise HubResponseError(
            f"포트 {port} 를 {'ON' if state else 'OFF'} 로 설정했으나 검증에 실패했습니다."
        )

    def __repr__(self) -> str:
        model = self._info.model if self._info else "?"
        return f"HubManager(name={self.name!r}, model={model!r})"
