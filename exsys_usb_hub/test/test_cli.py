"""CLI 검증.

- config 서브명령: main() 을 임시 경로로 호출해 검증.
- 허브 출력 명령: FakeHubSerial 기반 매니저로 cmd_* 를 직접 호출해 출력 검증.
"""

import os

from exsys_usb_hub import cli
from exsys_usb_hub.core import HubConfig, HubManager, SerialTransport

from fakes import FakeHubSerial


def _manager(hub):
    transport = SerialTransport(
        "/dev/fake", serial_factory=lambda port, **kw: hub, sleep=lambda d: None
    )
    mgr = HubManager(transport, sleep=lambda d: None)
    mgr.connect()
    return mgr


# ---------------------------------------------------------------------------
# config 서브명령
# ---------------------------------------------------------------------------
def test_config_init_creates_file(tmp_path, capsys):
    path = os.path.join(tmp_path, "exsys_hub.yaml")
    rc = cli.main(["-c", path, "config", "init"])
    assert rc == 0
    assert os.path.exists(path)
    assert "생성됨" in capsys.readouterr().out


def test_config_init_idempotent(tmp_path, capsys):
    path = os.path.join(tmp_path, "exsys_hub.yaml")
    cli.main(["-c", path, "config", "init"])
    capsys.readouterr()
    rc = cli.main(["-c", path, "config", "init"])
    assert rc == 0
    assert "이미 존재함" in capsys.readouterr().out


def test_config_set_and_show(tmp_path, capsys):
    path = os.path.join(tmp_path, "exsys_hub.yaml")
    cli.main(["-c", path, "config", "init"])
    cli.main(["-c", path, "config", "set", "port", "/dev/ttyUSB7"])
    capsys.readouterr()
    cli.main(["-c", path, "config", "show"])
    out = capsys.readouterr().out
    assert "/dev/ttyUSB7" in out


def test_config_set_port_name(tmp_path, capsys):
    path = os.path.join(tmp_path, "exsys_hub.yaml")
    cli.main(["-c", path, "config", "init"])
    cli.main(["-c", path, "config", "set", "port-name", "1", "Z-Wave", "Dongle"])
    cfg = HubConfig.load(path)
    assert cfg.port_name(1) == "Z-Wave Dongle"


def test_config_show_missing_file(tmp_path, capsys):
    path = os.path.join(tmp_path, "nope.yaml")
    rc = cli.main(["-c", path, "config", "show"])
    assert rc == 1


# ---------------------------------------------------------------------------
# 허브 출력 명령 (FakeHubSerial)
# ---------------------------------------------------------------------------
def test_cmd_info_output(capsys):
    mgr = _manager(FakeHubSerial(n_ports=4))
    cli.cmd_info(mgr, None)
    out = capsys.readouterr().out
    assert "CENTOS000104" in out
    assert "Ports    : 4" in out


def test_cmd_status_uses_labels(capsys):
    cfg = HubConfig.default()
    cfg.set_port_name(1, "Compute")
    mgr = _manager(FakeHubSerial(states=[True, False, False, False]))
    cli.cmd_status(mgr, cfg)
    out = capsys.readouterr().out
    assert "Compute (Port 1): ON" in out
    assert "Port 2: OFF" in out


def test_cmd_set_port_output(capsys):
    hub = FakeHubSerial(states=[False, False, False, False])
    mgr = _manager(hub)
    cli.cmd_set_port(mgr, 2, True, None)
    out = capsys.readouterr().out
    assert "OFF -> ON" in out
    assert hub.states[1] is True
