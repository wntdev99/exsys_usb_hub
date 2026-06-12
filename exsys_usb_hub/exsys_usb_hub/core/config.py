"""HubConfig — YAML 기반 설정 (ROS 비의존).

standalone/CLI 경로의 설정 소스다. ROS2 노드는 같은 값을 rclpy 파라미터로
받으므로 이 모듈을 쓰지 않는다 — 그래서 설정 소스가 환경별로 깔끔히 분리된다.

YAML 구조::

    device:
      port: /dev/exsys_hub
      baudrate: 9600
      timeout: 2
    safety:
      protected_ports: [1]
      inrush_delay_s: 0.5
      verify_retries: 2
    ports:
      1: "Compute"
      2: "Camera"
"""

from __future__ import annotations

import copy
import os
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyyaml 이 필요합니다: pip install pyyaml") from exc

_DEFAULT: dict[str, Any] = {
    "device": {
        "port": "/dev/exsys_hub",
        "baudrate": 9600,
        "timeout": 2,
    },
    "safety": {
        "protected_ports": [],
        "inrush_delay_s": 0.5,
        "verify_retries": 2,
    },
    "ports": {1: "", 2: "", 3: "", 4: ""},
}

_COMMENT_HEADER = """\
# Exsys USB Hub 설정
#
# device:
#   port     - 시리얼 포트 경로 (예: /dev/exsys_hub)
#   baudrate - 보드레이트 (장치 고정값 9600)
#   timeout  - 읽기 타임아웃(초)
#
# safety:
#   protected_ports - 차단(OFF)을 거부할 포트 번호 목록
#   inrush_delay_s  - OFF→ON 사이 최소 대기(초)
#   verify_retries  - set 후 read-back 검증 재시도 횟수
#
# ports:
#   각 포트에 표시용 라벨을 지정. 빈 문자열이면 "Port N" 사용.
#
"""


class HubConfig:
    """YAML 설정을 로드/수정/저장한다."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "HubConfig":
        return cls(copy.deepcopy(_DEFAULT))

    @classmethod
    def load(cls, path: str) -> "HubConfig":
        """YAML 파일에서 로드. 누락 키는 기본값과 병합한다."""
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"설정 파일이 없습니다: {path!r}\n"
                "`exsys_cli config init` 으로 생성하세요."
            )
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(_deep_merge(_DEFAULT, data))

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_COMMENT_HEADER)
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)

    # ------------------------------------------------------------------
    # device
    # ------------------------------------------------------------------

    @property
    def serial_port(self) -> str:
        return self._data["device"]["port"]

    @serial_port.setter
    def serial_port(self, value: str) -> None:
        self._data["device"]["port"] = value

    @property
    def baudrate(self) -> int:
        return int(self._data["device"].get("baudrate", 9600))

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        self._data["device"]["baudrate"] = int(value)

    @property
    def timeout(self) -> float:
        return float(self._data["device"].get("timeout", 2))

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._data["device"]["timeout"] = value

    # ------------------------------------------------------------------
    # safety
    # ------------------------------------------------------------------

    @property
    def protected_ports(self) -> list[int]:
        return list(self._data.get("safety", {}).get("protected_ports", []))

    @property
    def inrush_delay_s(self) -> float:
        return float(self._data.get("safety", {}).get("inrush_delay_s", 0.0))

    @property
    def verify_retries(self) -> int:
        return int(self._data.get("safety", {}).get("verify_retries", 2))

    # ------------------------------------------------------------------
    # 포트 이름
    # ------------------------------------------------------------------

    def port_name(self, port: int) -> str:
        return self._data.get("ports", {}).get(port) or ""

    def set_port_name(self, port: int, name: str) -> None:
        self._data.setdefault("ports", {})[port] = name

    def port_label(self, port: int) -> str:
        name = self.port_name(port)
        return f"{name} (Port {port})" if name else f"Port {port}"

    # ------------------------------------------------------------------
    # 표시
    # ------------------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return self._data

    def __repr__(self) -> str:
        return (
            f"HubConfig(port={self.serial_port!r}, baudrate={self.baudrate}, "
            f"protected_ports={self.protected_ports})"
        )


def _deep_merge(base: dict, override: dict) -> dict:
    """override 를 base 에 재귀 병합 (override 우선)."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
