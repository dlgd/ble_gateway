#!/usr/bin/env python3
"""Pluggable BLE scan backends.

Every backend is an advert *source*: it normalizes each advertisement into a
``BLEMessage`` and hands it to a single ``on_advert`` callback, so the
downstream filter/buffer/publish pipeline in ``ble_gateway`` is identical
regardless of which backend produced the advert.

Backends (selected by the ``scan_backend`` config key):

* ``bluez``     — the existing bleak/BlueZ scanner. Correct for adapters that
  support multi-PHY extended scanning (open-source controllers).
* ``hci_coded`` — a raw HCI-User-Channel scanner that scans **LE Coded PHY
  only** (``Scanning_PHYs=0x04``). Required for Nordic SoftDevice-Controller
  firmware, which rejects the kernel's mandatory 1M+Coded request.
* ``auto``      — try ``bluez``; on the multi-PHY rejection pattern fall back to
  ``hci_coded``.

The raw-HCI parsers (``parse_ext_adv_report`` / ``parse_ad_structures``) are
pure functions with no socket or bleak dependency, so they can be unit-tested
without hardware. ``bleak`` is imported lazily inside ``BlueZScanBackend`` for
the same reason.
"""

import abc
import asyncio
import ctypes
import fcntl
import logging
import os
import socket
import struct
import time
import uuid as uuidlib
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from ble_message import BLEMessage

# ---------------------------------------------------------------------------
# Raw HCI constants
# ---------------------------------------------------------------------------
AF_BLUETOOTH = 31
BTPROTO_HCI = 1
HCI_CHANNEL_USER = 1

# ioctls to bring an HCI device up/down (needs CAP_NET_ADMIN). Using these to
# down the adapter before binding HCI_CHANNEL_USER avoids depending on btmgmt,
# which can hang on SoftDevice-Controller firmware during a mgmt power-off.
HCIDEVUP = 0x400448C9
HCIDEVDOWN = 0x400448CA


class _SockaddrHci(ctypes.Structure):
    _fields_ = [
        ("hci_family", ctypes.c_ushort),
        ("hci_dev", ctypes.c_ushort),
        ("hci_channel", ctypes.c_ushort),
    ]


try:
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:  # pragma: no cover - non-glibc / non-Linux
    _libc = None


def _bind_hci_user_channel(sock, dev_id: int) -> None:
    """Bind an HCI socket to HCI_CHANNEL_USER on ``dev_id``.

    Python's native ``socket.bind`` HCI address format varies across CPython
    builds — some accept ``(dev, channel)``, others reject it with
    ``bind(): wrong format``. Bind the ``sockaddr_hci`` struct directly via libc
    (matching the validated reference) so it works regardless of the interpreter.
    """
    if _libc is not None:
        addr = _SockaddrHci(AF_BLUETOOTH, dev_id, HCI_CHANNEL_USER)
        ctypes.set_errno(0)
        if _libc.bind(sock.fileno(), ctypes.byref(addr), ctypes.sizeof(addr)) == 0:
            return
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    # Fallback: native bind (newer CPython accepts the 2-tuple form).
    sock.bind((dev_id, HCI_CHANNEL_USER))

# HCI command groups / opcodes (OGF, OCF)
OGF_HOST_CTL = 0x03
OGF_LE_CTL = 0x08
OCF_RESET = 0x0003
OCF_SET_EVENT_MASK = 0x0001
OCF_LE_SET_EVENT_MASK = 0x0001
OCF_LE_SET_RANDOM_ADDRESS = 0x0005
OCF_LE_SET_EXT_SCAN_PARAMS = 0x0041
OCF_LE_SET_EXT_SCAN_ENABLE = 0x0042

# LE Extended Advertising Report
HCI_EVENT_PKT = 0x04
HCI_LE_META_EVENT = 0x3E
HCI_SUBEVENT_EXT_ADV_REPORT = 0x0D

# Scanning_PHYs bit for LE Coded PHY (long range)
SCAN_PHY_CODED = 0x04

# AD structure types
AD_TYPE_UUID16_INCOMPLETE = 0x02
AD_TYPE_UUID16_COMPLETE = 0x03
AD_TYPE_UUID32_INCOMPLETE = 0x04
AD_TYPE_UUID32_COMPLETE = 0x05
AD_TYPE_UUID128_INCOMPLETE = 0x06
AD_TYPE_UUID128_COMPLETE = 0x07
AD_TYPE_NAME_SHORT = 0x08
AD_TYPE_NAME_COMPLETE = 0x09
AD_TYPE_TX_POWER = 0x0A
AD_TYPE_SERVICE_DATA_16 = 0x16
AD_TYPE_SERVICE_DATA_32 = 0x20
AD_TYPE_SERVICE_DATA_128 = 0x21
AD_TYPE_MANUFACTURER = 0xFF

# Bluetooth Base UUID — how bleak renders short (16/32-bit) UUIDs as full strings.
_BASE_UUID_SUFFIX = "-0000-1000-8000-00805f9b34fb"

DEFAULT_SCAN_BACKEND = "auto"
DEFAULT_HCI_SCAN_TYPE = "passive"
DEFAULT_HCI_INTERVAL = 0x0060
DEFAULT_HCI_WINDOW = 0x0060
DEFAULT_HCI_RANDOM_ADDR = "DE:DE:DE:DE:DE:C0"
DEFAULT_HCI_PROBE_SECONDS = 0.0

# Substrings (lower-cased) that identify the BlueZ multi-PHY rejection pattern
# bleak surfaces when the controller can't scan 1M+Coded together.
_MULTIPHY_REJECTION_MARKERS = (
    "inprogress",
    "in progress",
    "notready",
    "not ready",
    "not supported",
    "org.bluez.error",
)


# ---------------------------------------------------------------------------
# Pure parsers (no sockets, no bleak) — unit-testable
# ---------------------------------------------------------------------------
def _format_uuid128(le_bytes: bytes) -> str:
    """Format 16 little-endian UUID bytes as a canonical lowercase string.

    Matches bleak's representation exactly (e.g.
    ``"0000eff0-eff0-1212-1515-eeffd1024132"``) so whitelist matching and GPRP
    reconstruction behave identically to the BlueZ path.
    """
    return str(uuidlib.UUID(bytes=bytes(le_bytes[::-1])))


def _format_uuid_short(value: int, width_bytes: int) -> str:
    """Render a 16- or 32-bit UUID as the full Base-UUID string, like bleak."""
    if width_bytes == 2:
        return f"0000{value:04x}{_BASE_UUID_SUFFIX}"
    return f"{value:08x}{_BASE_UUID_SUFFIX}"


def parse_ad_structures(data: bytes) -> dict:
    """Parse length-prefixed AD structures from an advertising payload.

    Returns a dict with keys: ``name`` (str|None), ``service_uuids`` (list[str]),
    ``manufacturer_data`` (dict[int, bytes]), ``service_data`` (dict[str, bytes]),
    ``tx_power`` (int|None). Bounds-checked: malformed/truncated structures stop
    parsing rather than raising.
    """
    name: Optional[str] = None
    service_uuids: List[str] = []
    manufacturer_data: Dict[int, bytes] = {}
    service_data: Dict[str, bytes] = {}
    tx_power: Optional[int] = None

    i = 0
    n = len(data)
    while i < n:
        length = data[i]
        if length == 0:
            break
        # Need length more bytes after the length octet itself.
        if i + 1 + length > n:
            break
        ad_type = data[i + 1]
        payload = data[i + 2 : i + 1 + length]

        if ad_type in (AD_TYPE_NAME_SHORT, AD_TYPE_NAME_COMPLETE):
            name = payload.decode("utf-8", "replace")
        elif ad_type in (AD_TYPE_UUID128_INCOMPLETE, AD_TYPE_UUID128_COMPLETE):
            for off in range(0, len(payload) - 15, 16):
                service_uuids.append(_format_uuid128(payload[off : off + 16]))
        elif ad_type in (AD_TYPE_UUID16_INCOMPLETE, AD_TYPE_UUID16_COMPLETE):
            for off in range(0, len(payload) - 1, 2):
                val = int.from_bytes(payload[off : off + 2], "little")
                service_uuids.append(_format_uuid_short(val, 2))
        elif ad_type in (AD_TYPE_UUID32_INCOMPLETE, AD_TYPE_UUID32_COMPLETE):
            for off in range(0, len(payload) - 3, 4):
                val = int.from_bytes(payload[off : off + 4], "little")
                service_uuids.append(_format_uuid_short(val, 4))
        elif ad_type == AD_TYPE_MANUFACTURER:
            if len(payload) >= 2:
                company_id = int.from_bytes(payload[0:2], "little")
                manufacturer_data[company_id] = bytes(payload[2:])
        elif ad_type == AD_TYPE_SERVICE_DATA_16:
            if len(payload) >= 2:
                key = _format_uuid_short(int.from_bytes(payload[0:2], "little"), 2)
                service_data[key] = bytes(payload[2:])
        elif ad_type == AD_TYPE_SERVICE_DATA_32:
            if len(payload) >= 4:
                key = _format_uuid_short(int.from_bytes(payload[0:4], "little"), 4)
                service_data[key] = bytes(payload[4:])
        elif ad_type == AD_TYPE_SERVICE_DATA_128:
            if len(payload) >= 16:
                key = _format_uuid128(payload[0:16])
                service_data[key] = bytes(payload[16:])
        elif ad_type == AD_TYPE_TX_POWER:
            if len(payload) >= 1:
                tx_power = int.from_bytes(payload[0:1], "little", signed=True)

        i += 1 + length

    return {
        "name": name,
        "service_uuids": service_uuids,
        "manufacturer_data": manufacturer_data,
        "service_data": service_data,
        "tx_power": tx_power,
    }


def parse_ext_adv_report(pkt: bytes) -> Optional[dict]:
    """Parse a single HCI LE Extended Advertising Report event.

    Returns a dict with ``address``, ``address_type``, ``prim_phy``, ``rssi``
    and the parsed AD fields, or ``None`` if the packet is not a single-report
    extended advertising report or is truncated.

    Only ``Num_Reports == 1`` is handled (the common case for the Coded-PHY
    meter); multi-report packets are skipped.
    """
    if (
        len(pkt) < 5
        or pkt[0] != HCI_EVENT_PKT
        or pkt[1] != HCI_LE_META_EVENT
        or pkt[3] != HCI_SUBEVENT_EXT_ADV_REPORT
    ):
        return None
    if pkt[4] != 1:  # Num_Reports — only single-report packets supported
        return None

    p = pkt[5:]
    if len(p) < 24:  # fixed report fields up to and including Data_Length
        return None

    address_type = p[2]
    addr_le = p[3:9]
    address = ":".join(f"{b:02X}" for b in addr_le[::-1])
    prim_phy = p[9]
    rssi = int.from_bytes(p[13:14], "little", signed=True)
    data_len = p[23]
    if len(p) < 24 + data_len:
        return None
    data = p[24 : 24 + data_len]

    ad = parse_ad_structures(data)
    return {
        "address": address,
        "address_type": address_type,
        "prim_phy": prim_phy,
        "rssi": rssi,
        **ad,
    }


# ---------------------------------------------------------------------------
# Helpers shared by the gateway / backends
# ---------------------------------------------------------------------------
def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def build_ble_message_from_bleak(device, advertisement) -> BLEMessage:
    """Build a normalized BLEMessage from bleak's device + advertisement."""
    return BLEMessage(
        timestamp_ms=_now_ms(),
        device_address=device.address,
        # Prefer the name parsed from this advertisement; fall back to the
        # BlueZ-cached device name. The name (serial) is mandatory for V3
        # decryption, so don't rely solely on the cached value.
        device_name=advertisement.local_name or device.name,
        rssi=advertisement.rssi,
        manufacturer_data=dict(advertisement.manufacturer_data),
        service_data=dict(advertisement.service_data),
        service_uuids=list(advertisement.service_uuids),
        tx_power=advertisement.tx_power,
    )


def build_ble_message_from_report(report: dict) -> BLEMessage:
    """Build a normalized BLEMessage from a parsed extended advertising report."""
    return BLEMessage(
        timestamp_ms=_now_ms(),
        device_address=report["address"],
        device_name=report["name"],
        rssi=report["rssi"],
        manufacturer_data=report["manufacturer_data"],
        service_data=report["service_data"],
        service_uuids=report["service_uuids"],
        tx_power=report["tx_power"],
    )


def resolve_dev_id(config: dict) -> int:
    """Resolve the HCI device index (e.g. 0) from config.

    Prefers ``hci_coded.dev_id``; otherwise derives it from ``bluetooth_adapter``
    ("hci0" -> 0). Defaults to 0.
    """
    hci = config.get("hci_coded") or {}
    if "dev_id" in hci:
        return int(hci["dev_id"])
    adapter = config.get("bluetooth_adapter")
    if adapter:
        digits = "".join(ch for ch in str(adapter) if ch.isdigit())
        if digits:
            return int(digits)
    return 0


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------
class ScanBackend(abc.ABC):
    """Abstract advert source. Emits BLEMessage objects via ``on_advert``."""

    def __init__(
        self,
        config: dict,
        on_advert: Callable[[BLEMessage], None],
        logger: logging.Logger,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.config = config
        self.on_advert = on_advert
        self.logger = logger
        self.loop = loop

    @abc.abstractmethod
    async def start(self) -> None:
        """Start scanning. Raises on a fatal startup error."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop scanning and release resources. Best-effort, must not raise."""


class BlueZScanBackend(ScanBackend):
    """The existing bleak/BlueZ scanner, wrapped as a ScanBackend."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scanner = None

    def _detection_callback(self, device, advertisement) -> None:
        # bleak invokes this on the event-loop thread, so calling on_advert
        # directly keeps the buffer single-threaded.
        try:
            self.on_advert(build_ble_message_from_bleak(device, advertisement))
        except Exception as e:  # pragma: no cover - defensive
            self.logger.error(f"Error handling bleak advert: {e}")

    async def start(self) -> None:
        from bleak import BleakScanner  # lazy: keep parsers importable w/o bleak

        try:
            from bleak.args.bluez import BlueZScannerArgs

            bluez_available = True
        except ImportError:  # pragma: no cover - depends on bleak/platform
            BlueZScannerArgs = None
            bluez_available = False

        scanning_mode = self.config.get("scanning_mode", "active")
        duplicate_filtering = self.config.get("duplicate_filtering", True)

        scanner_kwargs = {}
        bluez_args = {}

        adapter = self.config.get("bluetooth_adapter")
        if adapter:
            self.logger.info(f"Using Bluetooth adapter: {adapter}")
            if bluez_available:
                bluez_args["adapter"] = adapter
            else:
                scanner_kwargs["adapter"] = adapter

        # Hardware-level service UUID filtering via SetDiscoveryFilter.
        service_uuids = None
        wl = self.config.get("service_uuid_whitelist")
        if wl:
            service_uuids = list(wl)
            self.logger.info(
                f"Hardware-level filtering enabled for {len(service_uuids)} "
                f"service UUID(s): {service_uuids}"
            )

        if bluez_available:
            bluez_args["filters"] = {"DuplicateData": not duplicate_filtering}
        self.logger.info(f"Duplicate filtering: {duplicate_filtering}")

        if bluez_args and bluez_available:
            scanner_kwargs["bluez"] = BlueZScannerArgs(**bluez_args)

        self._scanner = BleakScanner(
            detection_callback=self._detection_callback,
            service_uuids=service_uuids,
            scanning_mode=scanning_mode,
            **scanner_kwargs,
        )
        self.logger.info(f"Scan backend: bluez (mode={scanning_mode})")
        await self._scanner.start()

    async def stop(self) -> None:
        if self._scanner is not None:
            try:
                await self._scanner.stop()
            except Exception as e:  # pragma: no cover - defensive
                self.logger.warning(f"Error stopping bleak scanner: {e}")
            self._scanner = None


class HciCodedScanBackend(ScanBackend):
    """Raw HCI-User-Channel scanner, LE Coded PHY only.

    Reproduces the validated HCI sequence against nRF52840 SoftDevice-Controller
    firmware: power the adapter off so the kernel releases it, bind
    HCI_CHANNEL_USER, initialize the controller, then enable extended scanning
    with Scanning_PHYs=0x04 (Coded only). The blocking recv loop runs in a worker
    thread and marshals each advert onto the asyncio loop via call_soon_threadsafe.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import threading

        hci = self.config.get("hci_coded") or {}
        self.dev_id = resolve_dev_id(self.config)
        self.scan_type = (
            0x01
            if hci.get("scan_type", DEFAULT_HCI_SCAN_TYPE) == "active"
            else 0x00
        )
        self.interval = int(hci.get("interval", DEFAULT_HCI_INTERVAL))
        self.window = int(hci.get("window", DEFAULT_HCI_WINDOW))
        self.random_address = hci.get("random_address", DEFAULT_HCI_RANDOM_ADDR)
        self.power_on_at_shutdown = bool(hci.get("power_on_at_shutdown", True))

        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self._Thread = threading.Thread

    # -- HCI command helpers (run in worker thread / executor) --------------
    @staticmethod
    def _send_cmd(sock, ogf: int, ocf: int, params: bytes = b"") -> None:
        opcode = (ogf << 10) | ocf
        sock.send(struct.pack("<BHB", 0x01, opcode, len(params)) + params)

    def _cmd_sync(self, sock, ogf: int, ocf: int, params: bytes, label: str):
        """Send a command and wait for its Command Complete/Status. Returns
        the status byte, or None on timeout."""
        opcode = (ogf << 10) | ocf
        self._send_cmd(sock, ogf, ocf, params)
        end = time.time() + 2.0
        while time.time() < end:
            try:
                pkt = sock.recv(1024)
            except socket.timeout:
                break
            if len(pkt) < 7 or pkt[0] != HCI_EVENT_PKT:
                continue
            # Command Complete (0x0E)
            if pkt[1] == 0x0E and (pkt[4] | (pkt[5] << 8)) == opcode:
                return pkt[6]
            # Command Status (0x0F)
            if pkt[1] == 0x0F and (pkt[5] | (pkt[6] << 8)) == opcode:
                return pkt[3]
        self.logger.warning(f"HCI command '{label}' got no response")
        return None

    def _random_addr_le(self) -> bytes:
        """6-octet little-endian random address for LE Set Random Address."""
        raw = bytes.fromhex(self.random_address.replace(":", ""))
        return raw[::-1]  # config is MSB-first; wire wants LSB-first

    def _set_powered(self, up: bool) -> None:
        """Bring the HCI device up/down via ioctl (needs CAP_NET_ADMIN).

        Downing the device releases it from bluetoothd so HCI_CHANNEL_USER can
        bind; bringing it back up at shutdown lets bluetoothd manage it again.
        Best-effort: logs and continues on failure.
        """
        request = HCIDEVUP if up else HCIDEVDOWN
        try:
            ctl = socket.socket(
                AF_BLUETOOTH, socket.SOCK_RAW | socket.SOCK_CLOEXEC, BTPROTO_HCI
            )
            try:
                fcntl.ioctl(ctl.fileno(), request, self.dev_id)
            finally:
                ctl.close()
        except OSError as e:
            # EALREADY/EBUSY just mean it is already in the desired state.
            self.logger.debug(
                f"hci{self.dev_id} {'up' if up else 'down'} ioctl: {e}"
            )

    def _open_and_configure(self):
        """Power off the adapter, bind the user channel and start Coded scan.

        Synchronous (blocking) — called from an executor at startup and directly
        from the recv thread during recovery. Raises OSError on bind failure.
        """
        sock = None
        last_err = None
        # Down the controller, then bind the user channel. bluetoothd may briefly
        # race to re-power the device, so retry the down+bind a few times.
        for _ in range(10):
            self._set_powered(False)
            sock = socket.socket(
                AF_BLUETOOTH, socket.SOCK_RAW | socket.SOCK_CLOEXEC, BTPROTO_HCI
            )
            try:
                _bind_hci_user_channel(sock, self.dev_id)
                last_err = None
                break
            except OSError as e:
                last_err = e
                sock.close()
                sock = None
                time.sleep(0.2)
        if sock is None:
            raise OSError(
                f"bind HCI_CHANNEL_USER hci{self.dev_id} failed ({last_err}); "
                "ensure no other process holds the adapter and the process has "
                "CAP_NET_RAW+CAP_NET_ADMIN"
            ) from last_err

        sock.settimeout(2.0)
        # In user channel BlueZ no longer initializes the controller — do it here.
        self._cmd_sync(sock, OGF_HOST_CTL, OCF_RESET, b"", "HCI Reset")
        self._cmd_sync(
            sock, OGF_HOST_CTL, OCF_SET_EVENT_MASK, b"\xff" * 7 + b"\x3f", "Set Event Mask"
        )
        self._cmd_sync(
            sock, OGF_LE_CTL, OCF_LE_SET_EVENT_MASK, b"\xff" * 8, "LE Set Event Mask"
        )
        # A static random address is REQUIRED or scan enable returns 0x12.
        self._cmd_sync(
            sock,
            OGF_LE_CTL,
            OCF_LE_SET_RANDOM_ADDRESS,
            self._random_addr_le(),
            "LE Set Random Address",
        )
        # LE Set Extended Scan Parameters: own=Random, filter=all, Coded PHY only.
        params = struct.pack("<BBB", 0x01, 0x00, SCAN_PHY_CODED) + struct.pack(
            "<BHH", self.scan_type, self.interval, self.window
        )
        st = self._cmd_sync(
            sock, OGF_LE_CTL, OCF_LE_SET_EXT_SCAN_PARAMS, params, "scan params"
        )
        if st not in (0, None):
            sock.close()
            raise OSError(f"LE Set Extended Scan Parameters rejected (status 0x{st:02X})")
        # LE Set Extended Scan Enable: enable, no duplicate filtering (the
        # downstream throttle handles dedup; controller-level filtering with
        # duration=0 would suppress repeats indefinitely).
        st = self._cmd_sync(
            sock,
            OGF_LE_CTL,
            OCF_LE_SET_EXT_SCAN_ENABLE,
            struct.pack("<BBHH", 1, 0, 0, 0),
            "scan enable",
        )
        if st not in (0, None):
            sock.close()
            raise OSError(f"LE Set Extended Scan Enable rejected (status 0x{st:02X})")

        sock.settimeout(0.5)  # short timeout so the recv loop can poll _stop
        self._sock = sock
        self.logger.info(
            f"Scan backend: hci_coded (hci{self.dev_id}, Coded PHY only, "
            f"scan_type={'active' if self.scan_type else 'passive'})"
        )

    # -- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        self.loop = self.loop or asyncio.get_running_loop()
        self._stop.clear()
        await self.loop.run_in_executor(None, self._open_and_configure)
        self._thread = self._Thread(
            target=self._recv_loop, name="hci-coded-scan", daemon=True
        )
        self._thread.start()

    def _recv_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                pkt = self._sock.recv(1024)
            except socket.timeout:
                continue
            except OSError as e:
                if self._stop.is_set():
                    break
                self.logger.warning(f"HCI socket error ({e}); attempting recovery")
                self._safe_close()
                if not self._reopen_with_backoff():
                    break
                backoff = 1.0
                continue
            try:
                report = parse_ext_adv_report(pkt)
                if report is None:
                    continue
                msg = build_ble_message_from_report(report)
                self.loop.call_soon_threadsafe(self.on_advert, msg)
            except RuntimeError:
                # Event loop is closing during shutdown — drop the advert.
                break
            except Exception as e:  # pragma: no cover - defensive
                self.logger.debug(f"Failed to parse/dispatch advert: {e}")

    def _reopen_with_backoff(self) -> bool:
        """Re-init after a dongle replug. Returns False if asked to stop."""
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._open_and_configure()
                self.logger.info("HCI scan re-established after recovery")
                return True
            except Exception as e:
                self.logger.warning(
                    f"HCI re-open failed ({e}); retrying in {delay:.0f}s"
                )
                if self._stop.wait(delay):
                    return False
                delay = min(delay * 2, 30.0)
        return False

    def _safe_close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _shutdown_socket(self) -> None:
        sock = self._sock
        if sock is not None:
            try:
                # Best-effort: disable scanning before closing.
                self._send_cmd(
                    sock,
                    OGF_LE_CTL,
                    OCF_LE_SET_EXT_SCAN_ENABLE,
                    struct.pack("<BBHH", 0, 0, 0, 0),
                )
            except OSError:
                pass
        self._safe_close()

    async def stop(self) -> None:
        self._stop.set()
        loop = self.loop or asyncio.get_running_loop()
        await loop.run_in_executor(None, self._shutdown_socket)
        if self._thread is not None:
            await loop.run_in_executor(None, self._thread.join, 3.0)
            self._thread = None
        if self.power_on_at_shutdown:
            await loop.run_in_executor(None, self._set_powered, True)


class AutoScanBackend(ScanBackend):
    """Try bluez first; fall back to hci_coded on the multi-PHY rejection pattern."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active: Optional[ScanBackend] = None

    @staticmethod
    def _is_multiphy_rejection(exc: Exception) -> bool:
        s = str(exc).lower()
        return any(marker in s for marker in _MULTIPHY_REJECTION_MARKERS)

    async def _fall_back(self, reason: str) -> None:
        self.logger.warning(
            f"BlueZ scan unavailable ({reason}); falling back to hci_coded"
        )
        if self._active is not None:
            await self._active.stop()
        self._active = HciCodedScanBackend(
            self.config, self.on_advert, self.logger, loop=self.loop
        )
        await self._active.start()

    async def start(self) -> None:
        self.loop = self.loop or asyncio.get_running_loop()
        bluez = BlueZScanBackend(
            self.config, self.on_advert, self.logger, loop=self.loop
        )
        self._active = bluez
        try:
            await bluez.start()
        except Exception as e:
            if self._is_multiphy_rejection(e):
                await self._fall_back(str(e))
                return
            raise

        # Optional probe: if bluez accepts the scan but delivers nothing (e.g.
        # it can't do Coded PHY), fall back after probe_seconds. Off by default.
        hci = self.config.get("hci_coded") or {}
        probe_seconds = float(hci.get("probe_seconds", DEFAULT_HCI_PROBE_SECONDS))
        if probe_seconds > 0:
            seen = {"n": 0}
            real_cb = self.on_advert

            def counting_cb(msg):
                seen["n"] += 1
                real_cb(msg)

            bluez.on_advert = counting_cb
            self.logger.info(f"Probing BlueZ scan for {probe_seconds:.0f}s ...")
            await asyncio.sleep(probe_seconds)
            bluez.on_advert = real_cb
            if seen["n"] == 0:
                await self._fall_back("no adverts during probe window")

    async def stop(self) -> None:
        if self._active is not None:
            await self._active.stop()
            self._active = None


def create_scan_backend(
    config: dict,
    on_advert: Callable[[BLEMessage], None],
    logger: logging.Logger,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> ScanBackend:
    """Build the scan backend selected by ``config['scan_backend']``."""
    backend = config.get("scan_backend", DEFAULT_SCAN_BACKEND)
    if backend == "bluez":
        return BlueZScanBackend(config, on_advert, logger, loop=loop)
    if backend == "hci_coded":
        return HciCodedScanBackend(config, on_advert, logger, loop=loop)
    if backend == "auto":
        return AutoScanBackend(config, on_advert, logger, loop=loop)
    raise ValueError(f"Unknown scan_backend: {backend}")
