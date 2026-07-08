"""Tests for BLEMessage formatting and the HCI->BLEMessage->GPRP round-trip."""

import json

from helpers import ad_manufacturer, ad_name, ad_uuid128, build_ext_adv_report

from ble_message import BLEMessage
from scan_backends import (
    build_ble_message_from_report,
    parse_ad_structures,
    parse_ext_adv_report,
)

MOLLEAU_UUID = "0000eff0-eff0-1212-1515-eeffd1024132"


def _molleau_message(timestamp_ms=1_700_000_000_000):
    msg = BLEMessage(
        timestamp_ms=timestamp_ms,
        device_address="AA:BB:CC:DD:EE:FF",
        device_name="molleau_469430",
        rssi=-73,
        manufacturer_data={0x1234: b"\xde\xad\xbe\xef"},
        service_data={},
        service_uuids=[MOLLEAU_UUID],
        tx_power=None,
    )
    return msg


def test_gprp_format_pinned():
    msg = _molleau_message()
    out = json.loads(msg.to_gprp_format(gateway_mac="0011223344FF", topic="m/event"))
    assert out["mqtt_topic"] == "m/event"
    line = out["data"][0]
    parts = line.split(",")
    assert parts[0] == "$GPRP"
    assert parts[1] == "0011223344FF"
    assert parts[2] == "AABBCCDDEEFF"
    assert parts[3] == "-73"
    assert parts[5] == "1700000000.000"
    # advertising hex must round-trip back to the original components
    assert "EFF0" in parts[4].upper()


def test_hci_report_roundtrips_to_advertising_bytes():
    # Build the on-air AD payload, wrap as an HCI report, parse it back, build a
    # BLEMessage and confirm GPRP reconstruction reproduces the same AD bytes.
    ad = (
        ad_name("molleau_469430")
        + ad_uuid128(MOLLEAU_UUID)
        + ad_manufacturer(0x1234, b"\xde\xad\xbe\xef")
    )
    pkt = build_ext_adv_report("AA:BB:CC:DD:EE:FF", -73, ad)
    report = parse_ext_adv_report(pkt)
    msg = build_ble_message_from_report(report)

    assert msg.device_address == "AA:BB:CC:DD:EE:FF"
    assert msg.device_name == "molleau_469430"
    assert msg.rssi == -73
    assert msg.service_uuids == [MOLLEAU_UUID]
    assert msg.manufacturer_data == {0x1234: b"\xde\xad\xbe\xef"}

    # The reconstructed advertising data must equal the original on-air bytes
    # (same AD types and ordering: name, 128-bit UUID, manufacturer).
    assert msg._reconstruct_advertising_data() == ad


def test_service_data16_reconstructs_as_16bit_type():
    # A Base-UUID (short) key must be emitted as AD type 0x16 with a 2-byte UUID,
    # not 0x16 with the full 16-byte UUID (which corrupts the parsed payload).
    key = "0000fd6f-0000-1000-8000-00805f9b34fb"  # 16-bit UUID 0xFD6F
    msg = BLEMessage(
        timestamp_ms=0,
        device_address="AA:BB:CC:DD:EE:FF",
        device_name=None,
        rssi=-50,
        manufacturer_data={},
        service_data={key: b"\x01\x02\x03"},
        service_uuids=[],
        tx_power=None,
    )
    raw = msg._reconstruct_advertising_data()
    assert raw[1] == 0x16  # AD type: 16-bit service data
    assert raw[0] == 1 + 2 + 3  # type + 2 UUID bytes + 3 data bytes
    # Round-trips through the spec parser back to the same key/data.
    parsed = parse_ad_structures(raw)
    assert parsed["service_data"] == {key: b"\x01\x02\x03"}


def test_service_data128_reconstructs_as_128bit_type():
    key = "0000eff0-eff0-1212-1515-eeffd1024132"  # genuine 128-bit UUID
    msg = BLEMessage(
        timestamp_ms=0,
        device_address="AA:BB:CC:DD:EE:FF",
        device_name=None,
        rssi=-50,
        manufacturer_data={},
        service_data={key: b"\xaa\xbb"},
        service_uuids=[],
        tx_power=None,
    )
    raw = msg._reconstruct_advertising_data()
    assert raw[1] == 0x21  # AD type: 128-bit service data
    parsed = parse_ad_structures(raw)
    assert parsed["service_data"] == {key: b"\xaa\xbb"}


def test_short_service_uuid_reconstructs_as_16bit_list():
    key = "0000fd6f-0000-1000-8000-00805f9b34fb"
    msg = BLEMessage(
        timestamp_ms=0,
        device_address="AA:BB:CC:DD:EE:FF",
        device_name=None,
        rssi=-50,
        manufacturer_data={},
        service_data={},
        service_uuids=[key],
        tx_power=None,
    )
    raw = msg._reconstruct_advertising_data()
    assert raw[1] == 0x02  # incomplete list of 16-bit UUIDs
    parsed = parse_ad_structures(raw)
    assert parsed["service_uuids"] == [key]


def test_to_json_hex_encodes_bytes():
    msg = _molleau_message()
    out = json.loads(msg.to_json())
    assert out["manufacturer_data"] == {"4660": "deadbeef"}  # 0x1234 == 4660
    assert out["rssi"] == -73
