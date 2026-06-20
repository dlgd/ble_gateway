"""Tests for PayloadFilter operating on normalized BLEMessage objects."""

from ble_message import BLEMessage
from ble_gateway import PayloadFilter

MOLLEAU_UUID = "0000eff0-eff0-1212-1515-eeffd1024132"


def _msg(**overrides):
    base = dict(
        timestamp_ms=0,
        device_address="AA:BB:CC:DD:EE:FF",
        device_name="molleau_469430",
        rssi=-50,
        manufacturer_data={0x1234: b"\x01"},
        service_data={},
        service_uuids=[MOLLEAU_UUID],
        tx_power=None,
    )
    base.update(overrides)
    return BLEMessage(**base)


def test_no_whitelist_accepts_all():
    f = PayloadFilter()
    assert f.should_accept(_msg()) is True


def test_service_uuid_whitelist_match():
    f = PayloadFilter(service_uuid_whitelist={MOLLEAU_UUID})
    assert f.should_accept(_msg()) is True
    assert f.should_accept(_msg(service_uuids=[])) is False


def test_mac_whitelist_case_insensitive():
    f = PayloadFilter(mac_whitelist={"AA:BB:CC:DD:EE:FF"})
    # incoming address lower-cased still matches (filter upper-cases)
    assert f.should_accept(_msg(device_address="aa:bb:cc:dd:ee:ff")) is True
    assert f.should_accept(_msg(device_address="11:22:33:44:55:66")) is False


def test_name_whitelist_uses_device_name():
    f = PayloadFilter(name_whitelist={"molleau_469430"})
    assert f.should_accept(_msg()) is True
    assert f.should_accept(_msg(device_name="other")) is False
    assert f.should_accept(_msg(device_name=None)) is False


def test_manufacturer_id_whitelist():
    f = PayloadFilter(manufacturer_id_whitelist={0x1234})
    assert f.should_accept(_msg()) is True
    assert f.should_accept(_msg(manufacturer_data={0x9999: b"\x00"})) is False


def test_any_whitelist_match_accepts():
    f = PayloadFilter(
        mac_whitelist={"11:22:33:44:55:66"},
        service_uuid_whitelist={MOLLEAU_UUID},
    )
    # matches on UUID even though MAC differs
    assert f.should_accept(_msg(device_address="99:99:99:99:99:99")) is True
