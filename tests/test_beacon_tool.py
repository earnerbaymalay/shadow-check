"""The emulator beacon tool must keep producing packets the detector classifies as trackers."""
import importlib.util
from pathlib import Path

from shadowcheck.fingerprint import ble_fingerprint

spec = importlib.util.spec_from_file_location(
    "virtual_beacon", Path(__file__).parent.parent / "tools" / "virtual_beacon.py")
vb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vb)


def parse_ad(data):
    """Minimal AD-structure parser: returns (manufacturer_data, service_data, name)."""
    mfr, svc, name, i = {}, {}, None, 0
    while i < len(data) and data[i]:
        ln, typ, body = data[i], data[i + 1], data[i + 2:i + 1 + data[i]]
        if typ == 0xFF:
            mfr[int.from_bytes(body[:2], "little")] = bytes(body[2:])
        elif typ == 0x16:
            svc["0000%02x%02x-0000-1000-8000-00805f9b34fb" % (body[1], body[0])] = bytes(body[2:])
        elif typ == 0x09:
            name = body.decode()
        i += ln + 1
    return mfr, svc, name


def test_airtag_packet_is_detected():
    mfr, svc, name = parse_ad(vb.adv_payload("airtag", None))
    fp = ble_fingerprint("5A:11:22:33:44:55", "random", name, mfr, [], svc, None)
    assert fp.kind == "tracker" and "Find My" in fp.label


def test_tile_packet_is_detected():
    mfr, svc, name = parse_ad(vb.adv_payload("tile", None))
    fp = ble_fingerprint("6B:99:88:77:66:55", "random", name, mfr, [], svc, None)
    assert fp.kind == "tracker" and fp.label == "Tile tracker"


def test_watch_packet_is_not_a_tracker():
    mfr, svc, name = parse_ad(vb.adv_payload("watch", "Watch"))
    fp = ble_fingerprint("C1:00:00:00:00:01", "random", name, mfr, [], svc, None)
    assert fp.kind == "ble" and name == "Watch"


def test_airtag_advert_fits_in_31_bytes():
    assert len(vb.adv_payload("airtag", None)) <= 31
