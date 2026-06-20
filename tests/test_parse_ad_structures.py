"""Unit tests for the pure AD-structure parser (no sockets, no bleak)."""

from helpers import (
    ad_manufacturer,
    ad_name,
    ad_service_data16,
    ad_tx_power,
    ad_uuid128,
)

from scan_backends import parse_ad_structures

MOLLEAU_UUID = "0000eff0-eff0-1212-1515-eeffd1024132"


def test_name_decoded():
    out = parse_ad_structures(ad_name("molleau_469430"))
    assert out["name"] == "molleau_469430"


def test_uuid128_canonical_lowercase():
    out = parse_ad_structures(ad_uuid128(MOLLEAU_UUID))
    # Must match bleak's canonical lowercase hyphenated form exactly.
    assert out["service_uuids"] == [MOLLEAU_UUID]


def test_manufacturer_company_id_little_endian():
    out = parse_ad_structures(ad_manufacturer(0x004C, b"\xde\xad"))
    assert out["manufacturer_data"] == {0x004C: b"\xde\xad"}


def test_service_data16_key_is_base_uuid():
    out = parse_ad_structures(ad_service_data16(0xEFF0, b"\x01\x02\x03"))
    assert out["service_data"] == {
        "0000eff0-0000-1000-8000-00805f9b34fb": b"\x01\x02\x03"
    }


def test_tx_power_signed():
    out = parse_ad_structures(ad_tx_power(-12))
    assert out["tx_power"] == -12


def test_multiple_structures_combined():
    data = (
        ad_name("molleau_469430")
        + ad_uuid128(MOLLEAU_UUID)
        + ad_manufacturer(0x1234, b"\xaa\xbb\xcc")
    )
    out = parse_ad_structures(data)
    assert out["name"] == "molleau_469430"
    assert out["service_uuids"] == [MOLLEAU_UUID]
    assert out["manufacturer_data"] == {0x1234: b"\xaa\xbb\xcc"}


def test_truncated_structure_stops_safely():
    # length byte claims 10 bytes follow but only 2 are present
    data = bytes([0x0A, 0x09, 0x41, 0x42])
    out = parse_ad_structures(data)
    # Should not raise; truncated name structure is dropped.
    assert out["name"] is None


def test_zero_length_terminator():
    data = ad_name("ab") + b"\x00\x00\x00"
    out = parse_ad_structures(data)
    assert out["name"] == "ab"


def test_empty_input():
    out = parse_ad_structures(b"")
    assert out == {
        "name": None,
        "service_uuids": [],
        "manufacturer_data": {},
        "service_data": {},
        "tx_power": None,
    }
