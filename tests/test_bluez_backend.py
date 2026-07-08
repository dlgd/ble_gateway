"""Tests for BlueZScanBackend scanner-kwarg construction.

These fake out bleak's BleakScanner so start() can be driven without hardware
and we can assert exactly which kwargs the backend passes.
"""

import asyncio
import logging

import pytest

from scan_backends import BlueZScanBackend


def _logger():
    return logging.getLogger("test")


@pytest.fixture
def capture_scanner(monkeypatch):
    """Patch bleak.BleakScanner with a recorder and return the captured kwargs."""
    bleak = pytest.importorskip("bleak")
    captured = {}

    class FakeScanner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def start(self):
            pass

        async def stop(self):
            pass

    monkeypatch.setattr(bleak, "BleakScanner", FakeScanner)
    return captured


def test_adapter_passed_as_top_level_kwarg(capture_scanner):
    cfg = {"scan_backend": "bluez", "bluetooth_adapter": "hci1"}
    backend = BlueZScanBackend(cfg, lambda _m: None, _logger())
    asyncio.run(backend.start())

    # The adapter must reach BleakScanner directly, not the BlueZ TypedDict.
    assert capture_scanner.get("adapter") == "hci1"
    bluez = capture_scanner.get("bluez")
    if bluez is not None:
        assert "adapter" not in bluez


def test_no_adapter_kwarg_when_unset(capture_scanner):
    cfg = {"scan_backend": "bluez"}
    backend = BlueZScanBackend(cfg, lambda _m: None, _logger())
    asyncio.run(backend.start())

    assert "adapter" not in capture_scanner
