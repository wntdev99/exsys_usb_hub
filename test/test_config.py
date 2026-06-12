"""HubConfig 검증 — 기본값·왕복 저장/로드·안전 필드·포트 라벨."""

import os

from exsys_usb_hub.core.config import HubConfig


def test_defaults():
    cfg = HubConfig.default()
    assert cfg.serial_port == "/dev/exsys_hub"
    assert cfg.baudrate == 9600
    assert cfg.protected_ports == []
    assert cfg.inrush_delay_s == 0.5
    assert cfg.verify_retries == 2


def test_save_load_roundtrip(tmp_path):
    path = os.path.join(tmp_path, "exsys_hub.yaml")
    cfg = HubConfig.default()
    cfg.serial_port = "/dev/ttyUSB1"
    cfg.set_port_name(1, "Compute")
    cfg.save(path)

    loaded = HubConfig.load(path)
    assert loaded.serial_port == "/dev/ttyUSB1"
    assert loaded.port_name(1) == "Compute"


def test_load_merges_missing_keys(tmp_path):
    """일부 키만 있는 YAML 도 기본값과 병합되어 안전 필드가 채워진다."""
    path = os.path.join(tmp_path, "partial.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("device:\n  port: /dev/ttyUSB9\n")
    cfg = HubConfig.load(path)
    assert cfg.serial_port == "/dev/ttyUSB9"
    assert cfg.inrush_delay_s == 0.5      # 기본값으로 채워짐
    assert cfg.verify_retries == 2


def test_safety_fields_from_yaml(tmp_path):
    path = os.path.join(tmp_path, "safety.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("safety:\n  protected_ports: [1, 3]\n  inrush_delay_s: 1.5\n")
    cfg = HubConfig.load(path)
    assert cfg.protected_ports == [1, 3]
    assert cfg.inrush_delay_s == 1.5


def test_port_label():
    cfg = HubConfig.default()
    assert cfg.port_label(2) == "Port 2"
    cfg.set_port_name(2, "Camera")
    assert cfg.port_label(2) == "Camera (Port 2)"
