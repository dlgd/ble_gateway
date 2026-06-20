"""Tests for the backend factory and scan_backend config validation."""

import json

import pytest

from ble_gateway import load_config
from scan_backends import (
    AutoScanBackend,
    BlueZScanBackend,
    HciCodedScanBackend,
    create_scan_backend,
    resolve_dev_id,
)


def _noop(_msg):
    pass


def _logger():
    import logging

    return logging.getLogger("test")


@pytest.mark.parametrize(
    "backend,cls",
    [
        ("bluez", BlueZScanBackend),
        ("hci_coded", HciCodedScanBackend),
        ("auto", AutoScanBackend),
    ],
)
def test_factory_returns_expected_class(backend, cls):
    cfg = {"scan_backend": backend}
    assert isinstance(create_scan_backend(cfg, _noop, _logger()), cls)


def test_factory_defaults_to_auto():
    assert isinstance(create_scan_backend({}, _noop, _logger()), AutoScanBackend)


def test_factory_rejects_unknown():
    with pytest.raises(ValueError):
        create_scan_backend({"scan_backend": "bogus"}, _noop, _logger())


def test_resolve_dev_id_from_adapter():
    assert resolve_dev_id({"bluetooth_adapter": "hci3"}) == 3
    assert resolve_dev_id({"hci_coded": {"dev_id": 2}, "bluetooth_adapter": "hci3"}) == 2
    assert resolve_dev_id({}) == 0


def _write_cfg(tmp_path, extra):
    cfg = {"mqtt": {"broker": "localhost"}}
    cfg.update(extra)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return str(p)


def test_load_config_accepts_valid_hci(tmp_path):
    path = _write_cfg(
        tmp_path,
        {
            "scan_backend": "hci_coded",
            "hci_coded": {
                "dev_id": 0,
                "scan_type": "passive",
                "interval": 0x60,
                "window": 0x60,
                "random_address": "DE:DE:DE:DE:DE:C0",
                "power_on_at_shutdown": True,
                "probe_seconds": 0,
            },
        },
    )
    cfg = load_config(path)
    assert cfg["scan_backend"] == "hci_coded"


def test_load_config_rejects_bad_backend(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write_cfg(tmp_path, {"scan_backend": "nope"}))


def test_load_config_rejects_window_gt_interval(tmp_path):
    with pytest.raises(ValueError):
        load_config(
            _write_cfg(tmp_path, {"hci_coded": {"interval": 0x10, "window": 0x20}})
        )


def test_load_config_rejects_non_static_random_address(tmp_path):
    # 0x00 top bits -> not a static random address
    with pytest.raises(ValueError):
        load_config(
            _write_cfg(tmp_path, {"hci_coded": {"random_address": "00:11:22:33:44:55"}})
        )


def test_load_config_rejects_bad_scan_type(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write_cfg(tmp_path, {"hci_coded": {"scan_type": "sniff"}}))
