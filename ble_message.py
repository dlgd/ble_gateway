#!/usr/bin/env python3
"""Normalized BLE advertisement message.

`BLEMessage` is the single advert shape produced by every scan backend
(BlueZ/bleak or raw-HCI Coded-PHY) and consumed by the buffering/publishing
pipeline. Keeping it in its own module lets both `ble_gateway` and
`scan_backends` import it without a circular dependency, and lets the raw-HCI
parsers be unit-tested without pulling in bleak/BlueZ.
"""

import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

# BLE packet structure constants (AD types)
BLE_UUID_TYPE_INCOMPLETE_128 = 0x06
BLE_UUID_TYPE_COMPLETE_128 = 0x07  # AD type: complete list of 128-bit service UUIDs
BLE_TYPE_NAME_COMPLETE = 0x09  # AD type: complete local name (device serial for V3)
BLE_TYPE_MANUFACTURER_DATA = 0xFF
BLE_TYPE_SERVICE_DATA_16BIT = 0x16


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

        # Add service UUIDs (incomplete list of 128-bit UUIDs)
        if self.service_uuids:
            for uuid_str in self.service_uuids:
                # Remove hyphens and convert to bytes (little-endian for BLE)
                uuid_hex = uuid_str.replace("-", "")
                uuid_bytes = bytes.fromhex(uuid_hex)
                # Reverse for little-endian
                uuid_bytes_le = uuid_bytes[::-1]

                # Length = 1 (type) + 16 (UUID bytes)
                packet.append(17)
                packet.append(BLE_UUID_TYPE_INCOMPLETE_128)
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

        # Add service data (16-bit UUID service data)
        for uuid_str, data in self.service_data.items():
            uuid_hex = uuid_str.replace("-", "")
            uuid_bytes = bytes.fromhex(uuid_hex)

            # Length = 1 (type) + UUID bytes + data length
            length = 1 + len(uuid_bytes) + len(data)
            packet.append(length)
            packet.append(BLE_TYPE_SERVICE_DATA_16BIT)
            packet.extend(uuid_bytes[::-1])  # Little-endian
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
