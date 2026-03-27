"""Exsys Managed USB Hub — standalone CLI for Ubuntu (no Home Assistant required).

Usage:
    python exsys_cli.py -p /dev/ttyUSB0 info
    python exsys_cli.py -p /dev/ttyUSB0 status
    python exsys_cli.py -p /dev/ttyUSB0 on  <port>   # 1-indexed
    python exsys_cli.py -p /dev/ttyUSB0 off <port>   # 1-indexed
    python exsys_cli.py -p /dev/ttyUSB0 reset
    python exsys_cli.py -p /dev/ttyUSB0 factory-reset
    python exsys_cli.py -p /dev/ttyUSB0 save

Requirements:
    pip install pyserial
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import serial
from serial import SerialException

# ---------------------------------------------------------------------------
# Serial constants
# ---------------------------------------------------------------------------
BAUDRATE = 9600
BYTESIZE = 8
PARITY = "N"
STOPBITS = 1
TIMEOUT = 2  # seconds


# ---------------------------------------------------------------------------
# Low-level serial I/O
# ---------------------------------------------------------------------------

def _open(port: str) -> serial.Serial:
    try:
        ser = serial.Serial(
            port,
            baudrate=BAUDRATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
        )
        return ser
    except SerialException as exc:
        print(f"[error] Cannot open serial port {port!r}: {exc}", file=sys.stderr)
        sys.exit(1)


def _write_read(ser: serial.Serial, cmd: bytes) -> str:
    """Send cmd and return stripped UTF-8 response. Exits on failure."""
    try:
        ser.write(cmd)
        raw = ser.readline()
    except SerialException as exc:
        print(f"[error] Serial communication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not raw:
        print("[error] No response from device (timeout).", file=sys.stderr)
        sys.exit(1)

    return raw.decode("utf-8").strip()


# ---------------------------------------------------------------------------
# Protocol helpers  (ported from device.py, no HA dependency)
# ---------------------------------------------------------------------------

def _parse_hub_ports(message: str, n_ports: int) -> Optional[list[bool]]:
    """Decode 8-char hex response into a list of port states (port-order)."""
    if len(message) != 8:
        return None
    message = "".join(sum(zip(message[1::2], message[::2], strict=True), ()))
    message = message[::-1]
    message = int(message, 16)
    message = format(message, "b")[::-1]
    return [bool(int(c)) for c in message[:n_ports]]


def _message_from_hub_ports(ports: list[bool], n_ports: int) -> Optional[bytes]:
    """Encode port-state list into the SPpass... command bytes."""
    if len(ports) != n_ports:
        return None
    message = "".join([str(int(c)) for c in ports][::-1])
    message = int(message, 2)
    message = (message | 0xFFFFFFFF << n_ports) & 0xFFFFFFFF
    message = str(hex(message))[2:].upper()
    message = "".join(sum(zip(message[1::2], message[::2], strict=True), ()))
    message = message[::-1]
    return b"SPpass    " + message.encode() + b"\r"


# ---------------------------------------------------------------------------
# Hub commands
# ---------------------------------------------------------------------------

def get_hub_info(ser: serial.Serial) -> tuple[str, int, str]:
    """Return (model, n_ports, fw_version). Exits on failure."""
    response = _write_read(ser, b"?Q\r")
    if "v" not in response:
        print(f"[error] Unexpected response to ?Q: {response!r}", file=sys.stderr)
        sys.exit(1)
    device_type = response.split("v")[0]
    n_ports = int(device_type[-2:])
    fw_version = "v" + response.split("v")[1]
    return device_type, n_ports, fw_version


def get_hub_state(ser: serial.Serial, n_ports: int) -> list[bool]:
    """Return current port states. Exits on failure."""
    response = _write_read(ser, b"GP\r")
    states = _parse_hub_ports(response, n_ports)
    if states is None:
        print(f"[error] Unexpected response to GP: {response!r}", file=sys.stderr)
        sys.exit(1)
    return states


def set_port_state(
    ser: serial.Serial, port_idx: int, state: bool, n_ports: int
) -> list[bool]:
    """Set port_idx (0-based) to state. Returns updated port array. Exits on failure."""
    current = get_hub_state(ser, n_ports)
    current[port_idx] = state
    cmd = _message_from_hub_ports(current, n_ports)
    if cmd is None:
        print("[error] Failed to build set-port command.", file=sys.stderr)
        sys.exit(1)
    response = _write_read(ser, cmd)
    if not response or response[0] != "G":
        print(f"[error] Hub rejected set-port command: {response!r}", file=sys.stderr)
        sys.exit(1)
    return current


def reset_hub(ser: serial.Serial) -> None:
    _write_read(ser, b"RHpass    \r")


def restore_factory_defaults(ser: serial.Serial, n_ports: int) -> list[bool]:
    response = _write_read(ser, b"RDpass    \r")
    if not response or response[0] != "G":
        print(f"[error] Hub rejected factory-reset: {response!r}", file=sys.stderr)
        sys.exit(1)
    return get_hub_state(ser, n_ports)


def save_port_states(ser: serial.Serial) -> None:
    response = _write_read(ser, b"WPpass    \r")
    if not response or response[0] != "G":
        print(f"[error] Hub rejected save command: {response!r}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_info(ser: serial.Serial) -> None:
    model, n_ports, fw = get_hub_info(ser)
    print("[info]")
    print(f"  Model    : {model}")
    print(f"  Ports    : {n_ports}")
    print(f"  Firmware : {fw}")


def cmd_status(ser: serial.Serial) -> None:
    _, n_ports, _ = get_hub_info(ser)
    states = get_hub_state(ser, n_ports)
    print("[status]")
    for i, on in enumerate(states, start=1):
        print(f"  Port {i}: {'ON ' if on else 'OFF'}")


def cmd_set_port(ser: serial.Serial, port_number: int, state: bool) -> None:
    _, n_ports, _ = get_hub_info(ser)
    if not (1 <= port_number <= n_ports):
        print(f"[error] Port number must be between 1 and {n_ports}.", file=sys.stderr)
        sys.exit(1)
    port_idx = port_number - 1
    current = get_hub_state(ser, n_ports)
    prev = current[port_idx]
    updated = set_port_state(ser, port_idx, state, n_ports)
    label = "ON" if state else "OFF"
    prev_label = "ON" if prev else "OFF"
    status = "✓" if updated[port_idx] == state else "✗"
    print(f"  Port {port_number}: {prev_label} -> {label}  {status}")


def cmd_reset(ser: serial.Serial) -> None:
    reset_hub(ser)
    print("  Hub reset: OK")


def cmd_factory_reset(ser: serial.Serial) -> None:
    _, n_ports, _ = get_hub_info(ser)
    states = restore_factory_defaults(ser, n_ports)
    print("[factory-reset] OK — current port states after reset:")
    for i, on in enumerate(states, start=1):
        print(f"  Port {i}: {'ON ' if on else 'OFF'}")


def cmd_save(ser: serial.Serial) -> None:
    save_port_states(ser)
    print("  Port states saved as power-on defaults: OK")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="exsys_cli.py",
        description="Control Exsys Managed USB Hub over serial — no Home Assistant needed.",
    )
    parser.add_argument(
        "-p", "--port",
        required=True,
        metavar="SERIAL_PORT",
        help="Serial port path, e.g. /dev/ttyUSB0",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    sub.add_parser("info", help="Show device model, port count, and firmware version")
    sub.add_parser("status", help="Show all port states (ON/OFF)")

    on_p = sub.add_parser("on", help="Turn a port ON")
    on_p.add_argument("port_number", type=int, metavar="PORT", help="Port number (1-indexed)")

    off_p = sub.add_parser("off", help="Turn a port OFF")
    off_p.add_argument("port_number", type=int, metavar="PORT", help="Port number (1-indexed)")

    sub.add_parser("reset", help="Reset the hub")
    sub.add_parser("factory-reset", help="Restore factory defaults")
    sub.add_parser("save", help="Save current port states as power-on defaults")

    args = parser.parse_args()

    ser = _open(args.port)
    try:
        if args.command == "info":
            cmd_info(ser)
        elif args.command == "status":
            cmd_status(ser)
        elif args.command == "on":
            cmd_set_port(ser, args.port_number, True)
        elif args.command == "off":
            cmd_set_port(ser, args.port_number, False)
        elif args.command == "reset":
            cmd_reset(ser)
        elif args.command == "factory-reset":
            cmd_factory_reset(ser)
        elif args.command == "save":
            cmd_save(ser)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
