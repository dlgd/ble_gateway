"""Unit tests for the HCI Extended Advertising Report parser."""

from helpers import ad_manufacturer, ad_name, ad_uuid128, build_ext_adv_report

from scan_backends import parse_ext_adv_report

MOLLEAU_UUID = "0000eff0-eff0-1212-1515-eeffd1024132"


def _molleau_packet(rssi=-60):
    ad = (
        ad_name("molleau_469430")
        + ad_uuid128(MOLLEAU_UUID)
        + ad_manufacturer(0x1234, b"\xde\xad\xbe\xef")
    )
    return build_ext_adv_report("AA:BB:CC:DD:EE:FF", rssi, ad)


def test_full_report_fields():
    out = parse_ext_adv_report(_molleau_packet(rssi=-73))
    assert out is not None
    assert out["address"] == "AA:BB:CC:DD:EE:FF"  # reversed back, upper-case
    assert out["address_type"] == 0x01
    assert out["prim_phy"] == 0x03  # Coded PHY
    assert out["rssi"] == -73  # signed
    assert out["name"] == "molleau_469430"
    assert out["service_uuids"] == [MOLLEAU_UUID]
    assert out["manufacturer_data"] == {0x1234: b"\xde\xad\xbe\xef"}


def test_positive_rssi_decoded_signed():
    # 0xC4 unsigned = 196, but as signed int8 = -60.
    pkt = _molleau_packet(rssi=-60)
    assert parse_ext_adv_report(pkt)["rssi"] == -60


def test_rejects_non_le_meta():
    pkt = bytearray(_molleau_packet())
    pkt[1] = 0x3D  # not LE Meta
    assert parse_ext_adv_report(bytes(pkt)) is None


def test_rejects_wrong_subevent():
    pkt = bytearray(_molleau_packet())
    pkt[3] = 0x02  # not Extended Advertising Report
    assert parse_ext_adv_report(bytes(pkt)) is None


def test_rejects_multi_report():
    ad = ad_name("x")
    pkt = build_ext_adv_report("AA:BB:CC:DD:EE:FF", -50, ad, num_reports=2)
    assert parse_ext_adv_report(pkt) is None


def test_truncated_data_returns_none():
    pkt = _molleau_packet()
    # Chop off part of the advertising data payload (claimed Data_Length now lies).
    assert parse_ext_adv_report(pkt[:-5]) is None


def test_short_packet_returns_none():
    assert parse_ext_adv_report(b"\x04\x3e") is None
    assert parse_ext_adv_report(b"") is None
