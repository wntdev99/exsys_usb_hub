"""Exsys USB Hub CLI — ROS 없이 터미널에서 코어를 직접 구동한다.

사용 예::

    exsys_cli config init                 # 최초 1회 설정 생성
    exsys_cli status
    exsys_cli on 1
    exsys_cli off 2
    exsys_cli -p /dev/ttyUSB0 status      # 시리얼 포트 직접 지정
    exsys_cli -c /etc/exsys_hub.yaml info # 설정 파일 경로 지정

설정 없이도 ``-p`` 로 동작하며, 설정이 있으면 포트 라벨·보호 포트·인러시
지연이 자동 적용된다.
"""

from __future__ import annotations

import argparse
import os
import sys

from .core import HubConfig, HubError, HubManager, SerialTransport

DEFAULT_CONFIG = "exsys_hub.yaml"


# ---------------------------------------------------------------------------
# 매니저 빌드
# ---------------------------------------------------------------------------

def build_manager(serial_port: str, cfg: HubConfig | None) -> HubManager:
    """시리얼 포트와 (선택) 설정으로 HubManager 를 구성한다."""
    baudrate = cfg.baudrate if cfg else 9600
    timeout = cfg.timeout if cfg else 2.0
    transport = SerialTransport(serial_port, baudrate=baudrate, timeout=timeout)
    return HubManager(
        transport,
        protected_ports=cfg.protected_ports if cfg else (),
        inrush_delay_s=cfg.inrush_delay_s if cfg else 0.0,
        verify_retries=cfg.verify_retries if cfg else 2,
    )


# ---------------------------------------------------------------------------
# 허브 명령 (manager 를 받아 동작 — 테스트 용이)
# ---------------------------------------------------------------------------

def cmd_info(mgr: HubManager, cfg: HubConfig | None) -> None:
    d = mgr.info()
    print("[info]")
    print(f"  Model    : {d.model}")
    print(f"  Ports    : {d.n_ports}")
    print(f"  Firmware : {d.firmware}")


def cmd_status(mgr: HubManager, cfg: HubConfig | None) -> None:
    print("[status]")
    for i, on in enumerate(mgr.status(), start=1):
        label = cfg.port_label(i) if cfg else f"Port {i}"
        print(f"  {label}: {'ON ' if on else 'OFF'}")


def cmd_set_port(mgr: HubManager, port: int, state: bool, cfg: HubConfig | None) -> None:
    prev = mgr.get_port(port)
    mgr.set_port(port, state)
    label = cfg.port_label(port) if cfg else f"Port {port}"
    print(f"  {label}: {'ON' if prev else 'OFF'} -> {'ON' if state else 'OFF'}  ✓")


def cmd_reset(mgr: HubManager, cfg: HubConfig | None) -> None:
    mgr.reset()
    print("  Hub reset: OK")


def cmd_factory_reset(mgr: HubManager, cfg: HubConfig | None) -> None:
    states = mgr.factory_reset()
    print("[factory-reset] OK — 초기화 후 포트 상태:")
    for i, on in enumerate(states, start=1):
        label = cfg.port_label(i) if cfg else f"Port {i}"
        print(f"  {label}: {'ON ' if on else 'OFF'}")


def cmd_save(mgr: HubManager, cfg: HubConfig | None) -> None:
    mgr.save()
    print("  현재 상태를 전원-기본값으로 저장: OK")


# ---------------------------------------------------------------------------
# config 서브명령 (연결 불필요)
# ---------------------------------------------------------------------------

def cmd_config_init(path: str) -> None:
    if os.path.exists(path):
        print(f"[config] 이미 존재함: {path}")
        print("  기본값으로 재생성하려면 먼저 삭제하세요.")
        return
    HubConfig.default().save(path)
    print(f"[config] 생성됨: {path}")


def cmd_config_show(path: str) -> None:
    cfg = HubConfig.load(path)  # FileNotFoundError 는 상위에서 처리
    print(f"[config]  {path}")
    print(f"  device.port      : {cfg.serial_port}")
    print(f"  device.baudrate  : {cfg.baudrate}")
    print(f"  device.timeout   : {cfg.timeout}s")
    print(f"  protected_ports  : {cfg.protected_ports}")
    print(f"  inrush_delay_s   : {cfg.inrush_delay_s}")
    ports = cfg.as_dict().get("ports", {})
    if ports:
        print("  ports:")
        for num, name in sorted(ports.items()):
            print(f"    {num}: {name or '(unnamed)'}")


def cmd_config_set(path: str, key: str, value: str) -> None:
    try:
        cfg = HubConfig.load(path)
    except FileNotFoundError:
        cfg = HubConfig.default()
        print(f"[config] {path} 없음 — 기본값으로 생성합니다.")
    if key == "port":
        cfg.serial_port = value
    elif key == "baudrate":
        cfg.baudrate = int(value)
    elif key == "timeout":
        cfg.timeout = float(value)
    cfg.save(path)
    print(f"[config] {key} = {value}  ({path} 저장)")


def cmd_config_set_port_name(path: str, port: int, name: str) -> None:
    try:
        cfg = HubConfig.load(path)
    except FileNotFoundError:
        cfg = HubConfig.default()
        print(f"[config] {path} 없음 — 기본값으로 생성합니다.")
    cfg.set_port_name(port, name)
    cfg.save(path)
    print(f"[config] Port {port} name = {name!r}  ({path} 저장)")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _load_config_optional(path: str) -> HubConfig | None:
    return HubConfig.load(path) if os.path.exists(path) else None


def _resolve_serial_port(args, cfg: HubConfig | None) -> str:
    if args.port:
        return args.port
    if cfg:
        return cfg.serial_port
    print(
        "[error] 시리얼 포트가 지정되지 않았습니다.\n"
        "  -p /dev/ttyUSB0 를 쓰거나 `exsys_cli config init` 을 먼저 실행하세요.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exsys_cli",
        description="Exsys 관리형 USB 허브 제어 — ROS 불필요.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-p", "--port", metavar="SERIAL_PORT", default=None,
                        help="시리얼 포트 경로 (설정보다 우선). 예: /dev/ttyUSB0")
    parser.add_argument("-c", "--config", metavar="CONFIG_FILE", default=DEFAULT_CONFIG,
                        help=f"설정 파일 경로 (기본: {DEFAULT_CONFIG})")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    sub.add_parser("info", help="모델/포트수/펌웨어 표시")
    sub.add_parser("status", help="전체 포트 ON/OFF 상태")
    on_p = sub.add_parser("on", help="포트 ON")
    on_p.add_argument("port_number", type=int, metavar="PORT")
    off_p = sub.add_parser("off", help="포트 OFF")
    off_p.add_argument("port_number", type=int, metavar="PORT")
    sub.add_parser("reset", help="허브 리셋")
    sub.add_parser("factory-reset", help="공장 초기화")
    sub.add_parser("save", help="현재 상태를 전원-기본값으로 저장")

    cfg_p = sub.add_parser("config", help="설정 파일 관리")
    cfg_sub = cfg_p.add_subparsers(dest="config_action", metavar="ACTION")
    cfg_sub.required = True
    cfg_sub.add_parser("init", help="기본 설정 파일 생성")
    cfg_sub.add_parser("show", help="현재 설정 출력")
    set_p = cfg_sub.add_parser("set", help="설정 값 변경")
    set_p.add_argument("key", choices=["port", "baudrate", "timeout", "port-name"],
                       metavar="KEY")
    set_p.add_argument("value", nargs="+", metavar="VALUE",
                       help="값 (port-name 은: PORT_NUMBER NAME)")
    return parser


_HUB_COMMANDS = {
    "info": lambda mgr, cfg, args: cmd_info(mgr, cfg),
    "status": lambda mgr, cfg, args: cmd_status(mgr, cfg),
    "on": lambda mgr, cfg, args: cmd_set_port(mgr, args.port_number, True, cfg),
    "off": lambda mgr, cfg, args: cmd_set_port(mgr, args.port_number, False, cfg),
    "reset": lambda mgr, cfg, args: cmd_reset(mgr, cfg),
    "factory-reset": lambda mgr, cfg, args: cmd_factory_reset(mgr, cfg),
    "save": lambda mgr, cfg, args: cmd_save(mgr, cfg),
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ---- config 전용 명령 (연결 불필요) ----
    if args.command == "config":
        if args.config_action == "init":
            cmd_config_init(args.config)
        elif args.config_action == "show":
            try:
                cmd_config_show(args.config)
            except FileNotFoundError as e:
                print(f"[error] {e}", file=sys.stderr)
                return 1
        elif args.config_action == "set":
            if args.key == "port-name":
                if len(args.value) < 2:
                    print("[error] 사용법: config set port-name <PORT_NUMBER> <NAME>",
                          file=sys.stderr)
                    return 1
                cmd_config_set_port_name(args.config, int(args.value[0]),
                                         " ".join(args.value[1:]))
            else:
                cmd_config_set(args.config, args.key, args.value[0])
        return 0

    # ---- 허브 명령 (연결 필요) ----
    cfg = _load_config_optional(args.config)
    serial_port = _resolve_serial_port(args, cfg)
    try:
        with build_manager(serial_port, cfg) as mgr:
            _HUB_COMMANDS[args.command](mgr, cfg, args)
    except (HubError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
