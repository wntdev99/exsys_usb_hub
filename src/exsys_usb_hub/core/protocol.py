r"""Exsys 관리형 USB 허브의 순수 프로토콜 코덱.

이 모듈에는 **I/O 도 ROS 의존성도 전혀 없다.** 허브의 USB-시리얼 관리
프로토콜 와이어 포맷을 인코딩/디코딩하는 비트 연산만 담아, 하드웨어 없이
단위 테스트로 동결할 수 있게 한다. 가장 위험하고 이해하기 어려운 코드를
가장 먼저 못 박는 것이 리팩토링의 1순위다.

와이어 프로토콜 (9600 8N1)
--------------------------
====================  ============================================
명령 (host -> hub)     의미
====================  ============================================
``?Q\r``              모델 / 포트 수 / 펌웨어 조회
``GP\r``              전체 포트 상태 조회
``SPpass    <HEX>\r`` 전체 포트 상태 설정 (8자리 hex)
``RHpass    \r``      허브 리셋
``RDpass    \r``      공장 초기화
``WPpass    \r``      현재 상태를 전원-기본값으로 저장
====================  ============================================

포트 상태 와이어 인코딩
-----------------------
포트 상태는 32비트 값을 표현하는 8자리 hex 문자열로 전달된다. 니블/바이트
순서가 특이하다:

1. 인접한 hex 문자를 쌍 단위로 swap 한다.
2. 문자열 전체를 reverse 한다.
3. 결과 정수의 비트 순서는 포트 인덱스 기준 little-endian 이다
   (포트 1 == 최하위 비트).
4. set 명령에서는 ``n_ports`` 보다 높은 미사용 비트를 모두 1 로 채운다.

이 변환들은 서로 정확한 역연산이라, 모든 포트 상태 조합에 대해
``decode_port_states(encode_port_states(states)) == states`` 가 성립한다.
단, 라운드트립만으로는 "자기일관적이지만 틀린 변환"을 잡지 못하므로,
원본 구현에서 캡처한 골든 벡터(test 참조)로 와이어 포맷 자체를 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ProtocolError

# ---------------------------------------------------------------------------
# 와이어 상수
# ---------------------------------------------------------------------------
_HEX_WIDTH = 8                      # 포트-상태 hex 문자열 폭 (32비트)
_WORD_MASK = 0xFFFFFFFF             # 32비트 마스크

TERMINATOR = b"\r"

# 호스트 -> 허브 명령 (페이로드 없는 고정 명령)
CMD_QUERY_INFO = b"?Q" + TERMINATOR
CMD_GET_STATES = b"GP" + TERMINATOR
CMD_RESET = b"RHpass    " + TERMINATOR
CMD_FACTORY_RESET = b"RDpass    " + TERMINATOR
CMD_SAVE = b"WPpass    " + TERMINATOR

_SET_PREFIX = b"SPpass    "         # 뒤에 8자리 hex + TERMINATOR 가 붙는다

# 허브 -> 호스트 ACK 응답 머리글자 ('G' == granted/OK)
ACK_OK = "G"


@dataclass(frozen=True)
class HubInfo:
    """``?Q`` 응답을 파싱한 장치 메타데이터."""

    model: str
    n_ports: int
    firmware: str


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _swap_adjacent_pairs(text: str) -> str:
    """인접한 문자를 쌍 단위로 swap 한다. 입력 길이는 짝수여야 한다.

    예: ``"ABCD"`` -> ``"BADC"``.
    """
    if len(text) % 2 != 0:
        raise ProtocolError(f"hex 문자열 길이가 짝수가 아닙니다: {text!r}")
    return "".join(sum(zip(text[1::2], text[::2], strict=True), ()))


# ---------------------------------------------------------------------------
# 포트 상태 코덱
# ---------------------------------------------------------------------------

def decode_port_states(message: str, n_ports: int) -> list[bool]:
    """8자리 hex 응답을 포트 상태 리스트로 디코딩한다 (1-indexed: result[0] == 포트 1).

    Parameters
    ----------
    message:
        ``GP`` 응답의 8자리 hex 문자열.
    n_ports:
        허브의 포트 수. 반환 리스트 길이를 결정한다.

    Returns
    -------
    길이 ``n_ports`` 의 bool 리스트. ``True`` == ON.

    Raises
    ------
    ProtocolError
        길이가 8이 아니거나 hex 로 해석할 수 없는 경우.
    """
    if len(message) != _HEX_WIDTH:
        raise ProtocolError(
            f"포트 상태 응답은 {_HEX_WIDTH}자리여야 하는데 {len(message)}자리입니다: {message!r}"
        )
    try:
        value = int(_swap_adjacent_pairs(message)[::-1], 16)
    except ValueError as exc:
        raise ProtocolError(f"hex 디코딩 실패: {message!r}") from exc

    # 포트 인덱스 기준 little-endian → 비트 문자열을 뒤집고 n_ports 만큼 취한다.
    # 상위 비트가 0이어서 비트 폭이 모자라면 OFF(0)로 패딩한다.
    bits = format(value, "b")[::-1].ljust(n_ports, "0")
    return [bit == "1" for bit in bits[:n_ports]]


def encode_port_states(states: list[bool], n_ports: int) -> str:
    """포트 상태 리스트를 8자리 hex 문자열로 인코딩한다.

    Parameters
    ----------
    states:
        길이 ``n_ports`` 의 bool 리스트 (1-indexed: states[0] == 포트 1).
    n_ports:
        허브의 포트 수.

    Returns
    -------
    8자리 대문자 hex 문자열 (``SPpass`` 명령 본문).

    Raises
    ------
    ProtocolError
        ``len(states) != n_ports`` 인 경우.
    """
    if len(states) != n_ports:
        raise ProtocolError(
            f"포트 상태 개수({len(states)})가 포트 수({n_ports})와 다릅니다."
        )
    bits = "".join("1" if s else "0" for s in states)[::-1]
    value = int(bits, 2) if bits else 0
    # n_ports 이상의 미사용 비트는 1로 강제 (장치 규약).
    value = (value | (_WORD_MASK << n_ports)) & _WORD_MASK
    hex_str = format(value, "X").rjust(_HEX_WIDTH, "0")
    return _swap_adjacent_pairs(hex_str)[::-1]


def build_set_command(states: list[bool], n_ports: int) -> bytes:
    """포트 상태 리스트를 ``SPpass    <HEX>\\r`` 명령 바이트로 만든다."""
    body = encode_port_states(states, n_ports)
    return _SET_PREFIX + body.encode("ascii") + TERMINATOR


# ---------------------------------------------------------------------------
# 정보 응답 파싱
# ---------------------------------------------------------------------------

def parse_info_response(response: str) -> HubInfo:
    """``?Q`` 응답을 :class:`HubInfo` 로 파싱한다.

    응답 형식은 ``<MODEL>v<FIRMWARE>`` 이며, 모델명 끝 2자리가 포트 수다.
    예: ``"CENTOS000104v04"`` -> model=``"CENTOS000104"``, ports=4, fw=``"v04"``.

    Raises
    ------
    ProtocolError
        ``v`` 구분자가 없거나 포트 수를 파싱할 수 없는 경우.
    """
    if "v" not in response:
        raise ProtocolError(
            f"?Q 응답에 'v' 구분자가 없습니다 (Exsys 허브가 아닐 수 있음): {response!r}"
        )
    model, _, firmware_digits = response.partition("v")
    try:
        n_ports = int(model[-2:])
    except ValueError as exc:
        raise ProtocolError(
            f"모델명에서 포트 수를 파싱할 수 없습니다: {model!r}"
        ) from exc
    return HubInfo(model=model, n_ports=n_ports, firmware="v" + firmware_digits)


def is_ack(response: str) -> bool:
    """허브 응답이 성공 ACK('G' 로 시작)인지 검사한다."""
    return bool(response) and response[0] == ACK_OK
