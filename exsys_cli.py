"""Exsys USB Hub CLI — powered by the exsys_hub module.

Requirements:
    pip install pyserial pyyaml

Usage:
    # Config 초기화 (최초 1회)
    python exsys_cli.py config init

    # Config 기반 사용 (포트 지정 불필요)
    python exsys_cli.py info
    python exsys_cli.py status
    python exsys_cli.py on 1
    python exsys_cli.py off 2

    # 시리얼 포트 직접 지정 (config 없어도 동작)
    python exsys_cli.py -p /dev/ttyUSB0 status

    # config 파일 경로 지정
    python exsys_cli.py -c /etc/exsys_hub.yaml status

    # Config 관리
    python exsys_cli.py config show
    python exsys_cli.py config set port /dev/ttyUSB0
    python exsys_cli.py config set baudrate 9600
    python exsys_cli.py config set timeout 2
    python exsys_cli.py config set port-name 1 "Z-Wave Dongle"
"""

from __future__ import annotations

import argparse
import os
import sys

from exsys_hub import ExsysUsbHub, HubConfig, HubError

DEFAULT_CONFIG = "exsys_hub.yaml"


# ---------------------------------------------------------------------------
# Hub commands
# ---------------------------------------------------------------------------

def cmd_info(hub: ExsysUsbHub) -> None:
    d = hub.info()
    print("[info]")
    print(f"  Model    : {d['model']}")
    print(f"  Ports    : {d['ports']}")
    print(f"  Firmware : {d['firmware']}")


def cmd_status(hub: ExsysUsbHub, cfg: HubConfig | None) -> None:
    states = hub.status()
    print("[status]")
    for i, on in enumerate(states, start=1):
        label = cfg.port_label(i) if cfg else f"Port {i}"
        state_str = "ON " if on else "OFF"
        print(f"  {label}: {state_str}")


def cmd_set_port(hub: ExsysUsbHub, port: int, state: bool, cfg: HubConfig | None) -> None:
    prev = hub.get_port(port)
    if state:
        hub.on(port)
    else:
        hub.off(port)
    label = cfg.port_label(port) if cfg else f"Port {port}"
    prev_str = "ON" if prev else "OFF"
    new_str = "ON" if state else "OFF"
    print(f"  {label}: {prev_str} -> {new_str}  ✓")


def cmd_reset(hub: ExsysUsbHub) -> None:
    hub.reset()
    print("  Hub reset: OK")


def cmd_factory_reset(hub: ExsysUsbHub, cfg: HubConfig | None) -> None:
    states = hub.factory_reset()
    print("[factory-reset] OK — port states after reset:")
    for i, on in enumerate(states, start=1):
        label = cfg.port_label(i) if cfg else f"Port {i}"
        print(f"  {label}: {'ON ' if on else 'OFF'}")


def cmd_save(hub: ExsysUsbHub) -> None:
    hub.save()
    print("  Port states saved as power-on defaults: OK")


# ---------------------------------------------------------------------------
# Config subcommands
# ---------------------------------------------------------------------------

def cmd_config_init(config_path: str) -> None:
    if os.path.exists(config_path):
        print(f"[config] Already exists: {config_path}")
        print("  Delete it first if you want to reset to defaults.")
        return
    cfg = HubConfig.default()
    cfg.save(config_path)
    print(f"[config] Created: {config_path}")
    print("  Edit the file to set your serial port and port names.")


def cmd_config_show(config_path: str) -> None:
    try:
        cfg = HubConfig.load(config_path)
    except FileNotFoundError as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    d = cfg.as_dict()
    print(f"[config]  {config_path}")
    print(f"  device.port     : {cfg.serial_port}")
    print(f"  device.baudrate : {cfg.baudrate}")
    print(f"  device.timeout  : {cfg.timeout}s")
    ports = d.get("ports", {})
    if ports:
        print("  ports:")
        for num, name in sorted(ports.items()):
            display = name if name else "(unnamed)"
            print(f"    {num}: {display}")


def cmd_config_set(config_path: str, key: str, value: str) -> None:
    try:
        cfg = HubConfig.load(config_path)
    except FileNotFoundError:
        cfg = HubConfig.default()
        print(f"[config] {config_path} not found — creating with defaults.")

    if key == "port":
        cfg.serial_port = value
    elif key == "baudrate":
        cfg.baudrate = int(value)
    elif key == "timeout":
        cfg.timeout = int(value)
    else:
        print(f"[error] Unknown key {key!r}. Valid: port, baudrate, timeout", file=sys.stderr)
        sys.exit(1)

    cfg.save(config_path)
    print(f"[config] {key} = {value}  (saved to {config_path})")


def cmd_config_set_port_name(config_path: str, port: int, name: str) -> None:
    try:
        cfg = HubConfig.load(config_path)
    except FileNotFoundError:
        cfg = HubConfig.default()
        print(f"[config] {config_path} not found — creating with defaults.")

    cfg.set_port_name(port, name)
    cfg.save(config_path)
    print(f"[config] Port {port} name = {name!r}  (saved to {config_path})")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config_optional(config_path: str) -> HubConfig | None:
    """Load config if it exists, return None otherwise."""
    if os.path.exists(config_path):
        return HubConfig.load(config_path)
    return None


def _resolve_serial_port(args, cfg: HubConfig | None) -> str:
    """Return serial port: CLI flag > config file > error."""
    if args.port:
        return args.port
    if cfg:
        return cfg.serial_port
    print(
        "[error] No serial port specified.\n"
        "  Use -p /dev/ttyUSB0  or  run `python exsys_cli.py config init` first.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="exsys_cli.py",
        description="Control Exsys Managed USB Hub — no Home Assistant needed.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-p", "--port",
        metavar="SERIAL_PORT",
        default=None,
        help="Serial port path (overrides config). e.g. /dev/ttyUSB0",
    )
    parser.add_argument(
        "-c", "--config",
        metavar="CONFIG_FILE",
        default=DEFAULT_CONFIG,
        help=f"Config file path (default: {DEFAULT_CONFIG})",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # Hub commands
    sub.add_parser("info", help="Show device model, port count, firmware")
    sub.add_parser("status", help="Show all port ON/OFF states")

    on_p = sub.add_parser("on", help="Turn a port ON")
    on_p.add_argument("port_number", type=int, metavar="PORT")

    off_p = sub.add_parser("off", help="Turn a port OFF")
    off_p.add_argument("port_number", type=int, metavar="PORT")

    sub.add_parser("reset", help="Reset the hub")
    sub.add_parser("factory-reset", help="Restore factory defaults")
    sub.add_parser("save", help="Save current port states as power-on defaults")

    # Config subcommand group
    cfg_p = sub.add_parser("config", help="Manage config file")
    cfg_sub = cfg_p.add_subparsers(dest="config_action", metavar="ACTION")
    cfg_sub.required = True

    cfg_sub.add_parser("init", help="Create default config file")
    cfg_sub.add_parser("show", help="Print current config")

    set_p = cfg_sub.add_parser("set", help="Set a config value")
    set_p.add_argument(
        "key",
        choices=["port", "baudrate", "timeout", "port-name"],
        metavar="KEY",
        help="port | baudrate | timeout | port-name",
    )
    set_p.add_argument("value", nargs="+", metavar="VALUE",
                       help="Value (for port-name: PORT_NUMBER NAME)")

    args = parser.parse_args()

    # ---- Config-only commands (no hub connection needed) ----
    if args.command == "config":
        if args.config_action == "init":
            cmd_config_init(args.config)
        elif args.config_action == "show":
            cmd_config_show(args.config)
        elif args.config_action == "set":
            if args.key == "port-name":
                if len(args.value) < 2:
                    print("[error] Usage: config set port-name <PORT_NUMBER> <NAME>",
                          file=sys.stderr)
                    sys.exit(1)
                cmd_config_set_port_name(args.config, int(args.value[0]),
                                         " ".join(args.value[1:]))
            else:
                cmd_config_set(args.config, args.key, args.value[0])
        return

    # ---- Hub commands (need serial connection) ----
    cfg = _load_config_optional(args.config)
    serial_port = _resolve_serial_port(args, cfg)

    baudrate = cfg.baudrate if cfg else 9600
    timeout = cfg.timeout if cfg else 2

    try:
        with ExsysUsbHub(serial_port, baudrate=baudrate, timeout=timeout) as hub:
            if args.command == "info":
                cmd_info(hub)
            elif args.command == "status":
                cmd_status(hub, cfg)
            elif args.command == "on":
                cmd_set_port(hub, args.port_number, True, cfg)
            elif args.command == "off":
                cmd_set_port(hub, args.port_number, False, cfg)
            elif args.command == "reset":
                cmd_reset(hub)
            elif args.command == "factory-reset":
                cmd_factory_reset(hub, cfg)
            elif args.command == "save":
                cmd_save(hub)
    except (HubError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
