#!/usr/bin/env python3
"""Normalized BLE advertisement message.

`BLEMessage` is the single advert shape produced by every scan backend
(BlueZ/bleak or raw-HCI Coded-PHY) and consumed by the buffering/publishing
pipeline. Keeping it in its own module lets both `ble_gateway` and
`scan_backends` import it without a circular dependency, and lets the raw-HCI
parsers be unit-tested without pulling in bleak/BlueZ.
"""

import json
import struct
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

# BLE packet structure constants (AD types)
BLE_UUID_TYPE_INCOMPLETE_16 = 0x02
BLE_UUID_TYPE_INCOMPLETE_32 = 0x04
BLE_UUID_TYPE_INCOMPLETE_128 = 0x06
BLE_UUID_TYPE_COMPLETE_128 = 0x07  # AD type: complete list of 128-bit service UUIDs
BLE_TYPE_NAME_COMPLETE = 0x09  # AD type: complete local name (device serial for V3)
BLE_TYPE_MANUFACTURER_DATA = 0xFF
BLE_TYPE_SERVICE_DATA_16BIT = 0x16
BLE_TYPE_SERVICE_DATA_32BIT = 0x20
BLE_TYPE_SERVICE_DATA_128BIT = 0x21

# The Bluetooth Base UUID suffix. A 128-bit UUID string of the form
# 0000xxxx-0000-1000-8000-00805f9b34fb (or xxxxxxxx-...) is really a 16-/32-bit
# UUID and must be re-emitted at its native width, not padded to 128 bits.
_BASE_UUID_TAIL = "00001000800000805f9b34fb"


def _uuid_wire_form(uuid_str: str) -> Tuple[bytes, int]:
    """Return the minimal little-endian wire bytes and width for a UUID string.

    width is 2, 4 or 16 (bytes). Short (Base-UUID) forms collapse back to
    16/32-bit so the reconstructed AD structure is spec-faithful; anything else
    stays a full 128-bit UUID.
    """
    hexstr = uuid_str.replace("-", "").lower()
    if len(hexstr) == 32 and hexstr[8:] == _BASE_UUID_TAIL:
        value = int(hexstr[:8], 16)
        if value <= 0xFFFF:
            return struct.pack("<H", value), 2
        return struct.pack("<I", value), 4
    return bytes.fromhex(hexstr)[::-1], 16


@dataclass
class BLEMessage:
    """Structured BLE advertisement message."""

    timestamp_ms: int
    device_address: str
    device_name: Optional[str]
    rssi: int
    manufacturer_data: Dict[int, bytes]
    service_data: Dict[str, bytes]
    service_uuids: List[str]
    tx_power: Optional[int]

    def _reconstruct_advertising_data(self) -> bytes:
        """Reconstruct BLE advertising data from parsed components.

        Returns raw BLE advertising packet as bytes.
        """
        packet = bytearray()

        # Add complete local name (device serial). Required by the V3 decryption
        # path on the cloud side: the full serial is the input to both the
        # per-device key derivation and the AES-128-CCM nonce, so it must survive
        # reconstruction here or the payload can never be decrypted.
        if self.device_name:
            name_bytes = self.device_name.encode("utf-8")[:248]
            packet.append(1 + len(name_bytes))  # length = type + name bytes
            packet.append(BLE_TYPE_NAME_COMPLETE)
            packet.extend(name_bytes)

        # Add service UUIDs. Emit each at its native width (16/32/128-bit) so a
        # short UUID rendered as a Base-UUID string doesn't become a bogus
        # 128-bit list entry. Completeness is unknown after normalization, so we
        # emit the "incomplete" list type for each width.
        _uuid_list_type = {
            2: BLE_UUID_TYPE_INCOMPLETE_16,
            4: BLE_UUID_TYPE_INCOMPLETE_32,
            16: BLE_UUID_TYPE_INCOMPLETE_128,
        }
        if self.service_uuids:
            for uuid_str in self.service_uuids:
                uuid_bytes_le, width = _uuid_wire_form(uuid_str)
                # Length = 1 (type) + width (UUID bytes)
                packet.append(1 + width)
                packet.append(_uuid_list_type[width])
                packet.extend(uuid_bytes_le)

        # Add manufacturer specific data
        for company_id, data in self.manufacturer_data.items():
            # Length = 1 (type) + 2 (company ID) + data length
            length = 1 + 2 + len(data)
            packet.append(length)
            packet.append(BLE_TYPE_MANUFACTURER_DATA)
            # Company ID in little-endian
            packet.append(company_id & 0xFF)
            packet.append((company_id >> 8) & 0xFF)
            packet.extend(data)

        # Add service data with the AD type matching the UUID width. A short
        # (Base-UUID) key becomes type 0x16 (16-bit) / 0x20 (32-bit); a genuine
        # 128-bit UUID becomes type 0x21. Previously every entry was emitted as
        # 0x16 with the full 16-byte UUID, which a spec parser reads as a 2-byte
        # UUID followed by 14 junk payload bytes.
        _service_data_type = {
            2: BLE_TYPE_SERVICE_DATA_16BIT,
            4: BLE_TYPE_SERVICE_DATA_32BIT,
            16: BLE_TYPE_SERVICE_DATA_128BIT,
        }
        for uuid_str, data in self.service_data.items():
            uuid_bytes_le, width = _uuid_wire_form(uuid_str)
            # Length = 1 (type) + UUID bytes + data length
            length = 1 + width + len(data)
            packet.append(length)
            packet.append(_service_data_type[width])
            packet.extend(uuid_bytes_le)  # Little-endian
            packet.extend(data)

        return bytes(packet)

    def to_gprp_format(self, gateway_mac: str, topic: str) -> str:
        """Convert to GPRP CSV format wrapped in JSON.

        Format: $GPRP,<gateway_mac>,<device_mac>,<rssi>,<ble_advertising_hex>,<timestamp>

        Args:
            gateway_mac: Gateway MAC address (12 hex chars, no separators)
            topic: MQTT topic name

        Returns:
            JSON string with data array and mqtt_topic
        """
        # Reconstruct raw advertising data
        advertising_hex = self._reconstruct_advertising_data().hex().upper()

        # Convert timestamp from ms to seconds with decimal
        timestamp_sec = self.timestamp_ms / 1000.0

        # Remove colons from device MAC address
        device_mac = self.device_address.replace(":", "").upper()

        # Build GPRP CSV line
        gprp_line = f"$GPRP,{gateway_mac},{device_mac},{self.rssi},{advertising_hex},{timestamp_sec:.3f}"

        # Wrap in JSON structure
        return json.dumps(
            {"data": [gprp_line], "mqtt_topic": topic}, separators=(",", ":")
        )

    def to_json(self) -> str:
        """Convert to JSON string with hex-encoded bytes."""
        data = asdict(self)
        # Convert bytes to hex strings
        data["manufacturer_data"] = {
            str(k): v.hex() for k, v in self.manufacturer_data.items()
        }
        data["service_data"] = {k: v.hex() for k, v in self.service_data.items()}
        return json.dumps(data, separators=(",", ":"))
