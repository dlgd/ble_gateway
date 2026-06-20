"""Builders for synthetic HCI advertising packets used in tests."""

import struct
import uuid as uuidlib


def ad_struct(ad_type: int, payload: bytes) -> bytes:
    """Build one length-prefixed AD structure."""
    return bytes([1 + len(payload), ad_type]) + payload


def ad_name(name: str) -> bytes:
    return ad_struct(0x09, name.encode("utf-8"))


def ad_uuid128(uuid_str: str) -> bytes:
    """Complete-list-of-128-bit-UUIDs AD structure (little-endian on wire)."""
    raw = uuidlib.UUID(uuid_str).bytes  # big-endian
    return ad_struct(0x06, raw[::-1])


def ad_manufacturer(company_id: int, data: bytes) -> bytes:
    return ad_struct(0xFF, struct.pack("<H", company_id) + data)


def ad_service_data16(uuid16: int, data: bytes) -> bytes:
    return ad_struct(0x16, struct.pack("<H", uuid16) + data)


def ad_tx_power(dbm: int) -> bytes:
    return ad_struct(0x0A, struct.pack("<b", dbm))


def build_ext_adv_report(
    address: str,
    rssi: int,
    ad_data: bytes,
    *,
    addr_type: int = 0x01,
    prim_phy: int = 0x03,  # 0x03 = LE Coded
    num_reports: int = 1,
) -> bytes:
    """Build a full HCI LE Extended Advertising Report event packet.

    address is given MSB-first ("AA:BB:..."); it is stored little-endian on wire.
    """
    addr_le = bytes.fromhex(address.replace(":", ""))[::-1]
    report = bytearray()
    report += struct.pack("<H", 0)          # Event_Type (2)
    report += bytes([addr_type])            # Address_Type (1)
    report += addr_le                       # Address (6, LE)
    report += bytes([prim_phy])             # Primary_PHY (1)
    report += bytes([prim_phy])             # Secondary_PHY (1)
    report += bytes([0x00])                 # Advertising_SID (1)
    report += bytes([0x7F])                 # TX_Power (1, unavailable)
    report += struct.pack("<b", rssi)       # RSSI (1, signed)
    report += struct.pack("<H", 0)          # Periodic_Adv_Interval (2)
    report += bytes([0x00])                 # Direct_Address_Type (1)
    report += bytes(6)                       # Direct_Address (6)
    report += bytes([len(ad_data)])         # Data_Length (1)
    report += ad_data                        # Data

    body = bytes([HCI_SUBEVENT := 0x0D, num_reports]) + bytes(report)
    return bytes([0x04, 0x3E, len(body)]) + body
