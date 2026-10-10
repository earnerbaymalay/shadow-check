import struct

from shadowcheck.engine import analyze
from shadowcheck.fingerprint import address_class, ble_fingerprint, wifi_fingerprint
from shadowcheck.wifi import parse_probe_request

T0 = 1_750_000_000.0


def probe_frame(mac, ssid, signal=-48):
    # radiotap: ver, pad, len=9, present=flags(bit1)+dBm signal(bit5); flags=0, signal
    rt = struct.pack("<BBHIBb", 0, 0, 10, (1 << 1) | (1 << 5), 0, signal)
    dot11 = bytes([0x40, 0x00, 0, 0]) + b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) \
        + b"\xff" * 6 + b"\x00\x00"
    ssid_b = ssid.encode()
    ies = bytes([0, len(ssid_b)]) + ssid_b + bytes([1, 4, 0x02, 0x04, 0x0B, 0x16]) \
        + bytes([45, 2, 0xAA, 0xBB])
    return rt + dot11 + ies


def rows(fp, kind, strength, sightings, rssi=-50, label=""):
    """sightings: [(place, start_offset_s, n_obs)] each obs 20 s apart."""
    out = []
    for place, off, n in sightings:
        for i in range(n):
            out.append((T0 + off + i * 20, fp, kind, strength, rssi, place, None, None, label))
    return out


# --- wifi parsing -----------------------------------------------------------

def test_parse_probe_request():
    mac, rssi, ssid, ie_hash = parse_probe_request(probe_frame("da:a1:19:00:11:22", "HomeNet"))
    assert mac == "da:a1:19:00:11:22" and rssi == -48 and ssid == "HomeNet" and ie_hash


def test_non_probe_frame_ignored():
    f = bytearray(probe_frame("da:a1:19:00:11:22", ""))
    f[10] = 0x80  # beacon
    assert parse_probe_request(bytes(f)) is None


def test_same_model_same_layout_hash():
    a = parse_probe_request(probe_frame("da:a1:19:00:00:01", ""))
    b = parse_probe_request(probe_frame("da:a1:19:00:00:02", ""))
    assert a[3] == b[3]  # identical capabilities -> weak, shared fingerprint


def test_wifi_strength():
    assert wifi_fingerprint("a0:51:0b:af:b8:ec", "x", "").strength == 1.0   # global MAC
    assert wifi_fingerprint("da:a1:19:00:00:01", "x", "").strength == 0.25   # random, broadcast
    assert wifi_fingerprint("da:a1:19:00:00:01", "x", "Net").strength == 0.6  # random, directed


# --- ble fingerprinting -----------------------------------------------------

def test_address_classes():
    assert address_class("A0:51:0B:AF:B8:F0", "public") == "public"
    assert address_class("C1:00:00:00:00:01", "random") == "static"
    assert address_class("5A:00:00:00:00:01", "random") == "rpa"
    assert address_class("1A:00:00:00:00:01", "random") == "nrpa"


def test_airtag_style_advert_is_tracker():
    # Apple company id 0x004C, Find My offline-finding type 0x12, length 0x19
    payload = bytes([0x12, 0x19, 0x10]) + bytes(24)
    fp = ble_fingerprint("5A:11:22:33:44:55", "random", None, {0x004C: payload}, [])
    assert fp.kind == "tracker"


def test_tile_uuid_is_tracker():
    fp = ble_fingerprint("5A:11:22:33:44:55", "random", None, {},
                         ["0000feed-0000-1000-8000-00805f9b34fb"])
    assert fp.kind == "tracker"


def test_rotating_address_not_used_as_identity():
    a = ble_fingerprint("5A:11:22:33:44:55", "random", "Pixel 8", {0x00E0: b"\x01\x02"}, [])
    b = ble_fingerprint("6B:99:88:77:66:55", "random", "Pixel 8", {0x00E0: b"\x09\x09"}, [])
    assert a.fp == b.fp  # same traits across rotated addresses link up


# --- engine -----------------------------------------------------------------

def test_follower_across_places_is_high():
    r = rows("wifi:stalker", "wifi", 1.0, [("Home", 0, 6), ("Gym", 86400, 6), ("Hotel", 2 * 86400, 6)])
    f = analyze(r)
    assert f and f[0].level == "HIGH" and len(f[0].places) == 3


def test_single_place_device_ignored():
    r = rows("wifi:neighbour", "wifi", 1.0, [("Home", 0, 10), ("Home", 86400, 10)])
    assert analyze(r) == []


def test_allowlisted_device_ignored():
    r = rows("wifi:driver", "wifi", 1.0, [("Home", 0, 6), ("Gym", 86400, 6), ("Hotel", 2 * 86400, 6)])
    assert analyze(r, allowed={"wifi:driver"}) == []


def test_passerby_not_meaningful():
    # two places but each encounter is a single observation
    r = rows("wifi:passer", "wifi", 1.0, [("Home", 0, 1), ("Gym", 86400, 1)])
    assert analyze(r) == []


def test_weak_fingerprint_discounted():
    strong = rows("a", "wifi", 1.0, [("Home", 0, 6), ("Gym", 86400, 6)])
    weak = rows("b", "wifi", 0.25, [("Home", 0, 6), ("Gym", 86400, 6)])
    assert analyze(strong) and not analyze(weak)


def test_tracker_moving_is_high():
    r = rows("trk:x", "tracker", 0.9, [("Home", 0, 6), ("Mall", 3600, 6)], label="AirTag")
    assert analyze(r)[0].level == "HIGH"


def test_tracker_stationary_long_dwell_is_medium():
    r = rows("trk:x", "tracker", 0.9, [("Home", 0, 80)])  # 80 obs * 20 s ~ 26 min
    assert analyze(r)[0].level == "MEDIUM"


def test_distant_signal_scores_lower_than_close():
    near = rows("n", "wifi", 1.0, [("A", 0, 6), ("B", 86400, 6)], rssi=-40)
    far = rows("f", "wifi", 1.0, [("A", 0, 6), ("B", 86400, 6)], rssi=-85)
    assert analyze(near)[0].score > analyze(far)[0].score
