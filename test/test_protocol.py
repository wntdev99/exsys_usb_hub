"""순수 프로토콜 코덱 동결 테스트.

목적은 두 가지다.

1. **골든 벡터** — 원본 구현(``exsys_hub/hub.py``)에서 캡처한 실제 와이어
   출력값을 박아, 비트 변환을 "정리"하다 와이어 포맷이 바뀌면 즉시 잡는다.
   (라운드트립만으로는 자기일관적이지만 틀린 변환을 못 잡는다.)
2. **라운드트립** — 모든 포트 조합에서 ``decode(encode(x)) == x`` 임을 증명한다.
"""

import itertools

import pytest

from exsys_usb_hub.core import protocol as p
from exsys_usb_hub.core.errors import ProtocolError


# ---------------------------------------------------------------------------
# 골든 벡터 — 원본 _message_from_hub_ports 에서 캡처 (n_ports=4)
#   key: 포트 상태(1=ON, index0=포트1),  value: 8자리 hex 본문
# ---------------------------------------------------------------------------
GOLDEN_N4 = {
    (False, False, False, False): "F0FFFFFF",
    (True, False, False, False): "F1FFFFFF",   # 포트1 ON
    (False, True, False, False): "F2FFFFFF",   # 포트2 ON
    (False, False, False, True): "F8FFFFFF",   # 포트4 ON
    (True, True, True, True): "FFFFFFFF",       # 전체 ON
    (True, False, True, False): "F5FFFFFF",
}


@pytest.mark.parametrize("states,expected_hex", GOLDEN_N4.items())
def test_encode_golden_n4(states, expected_hex):
    """인코딩 결과가 원본 와이어 포맷과 바이트 단위로 일치한다."""
    assert p.encode_port_states(list(states), 4) == expected_hex


@pytest.mark.parametrize("states,wire_hex", GOLDEN_N4.items())
def test_decode_golden_n4(states, wire_hex):
    """골든 hex 를 디코딩하면 원래 포트 상태로 돌아온다."""
    assert p.decode_port_states(wire_hex, 4) == list(states)


def test_build_set_command_bytes():
    """SPpass 명령 전체 바이트(프리픽스+hex+CR)를 고정한다."""
    cmd = p.build_set_command([True, False, False, False], 4)
    assert cmd == b"SPpass    F1FFFFFF\r"


# ---------------------------------------------------------------------------
# 라운드트립 — 모든 조합에서 decode(encode(x)) == x
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n_ports", [4, 7, 8, 16])
def test_roundtrip_exhaustive(n_ports):
    # n<=16 이면 2^16=65536 조합까지 전수 검증 (빠름).
    for combo in itertools.product([False, True], repeat=n_ports):
        states = list(combo)
        wire = p.encode_port_states(states, n_ports)
        assert len(wire) == 8
        assert p.decode_port_states(wire, n_ports) == states


# ---------------------------------------------------------------------------
# 에러 경로
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "F1FFFFF", "F1FFFFFFF", "ZZZZZZZZ"])
def test_decode_rejects_bad_input(bad):
    with pytest.raises(ProtocolError):
        p.decode_port_states(bad, 4)


def test_encode_rejects_wrong_length():
    with pytest.raises(ProtocolError):
        p.encode_port_states([True, False], 4)


def test_swap_rejects_odd_length():
    with pytest.raises(ProtocolError):
        p._swap_adjacent_pairs("ABC")


# ---------------------------------------------------------------------------
# ?Q 정보 응답 파싱
# ---------------------------------------------------------------------------
def test_parse_info_response():
    info = p.parse_info_response("CENTOS000104v04")
    assert info.model == "CENTOS000104"
    assert info.n_ports == 4
    assert info.firmware == "v04"


def test_parse_info_rejects_missing_v():
    with pytest.raises(ProtocolError):
        p.parse_info_response("CENTOS000104")


def test_parse_info_rejects_bad_port_count():
    with pytest.raises(ProtocolError):
        p.parse_info_response("MODELXXv04")


# ---------------------------------------------------------------------------
# ACK 판별
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("resp,expected", [("G", True), ("GOOD", True), ("E", False), ("", False)])
def test_is_ack(resp, expected):
    assert p.is_ack(resp) is expected
