"""Turn radio metadata into a stable pseudonymous fingerprint.

Phones randomize addresses, so identity is inferred from what stays constant:
a real (global) MAC when present, otherwise a hash of device-model traits.
`strength` (0..1) says how unique the fingerprint is; weak ones collide across
many identical phones and are discounted by the scoring engine.
"""
import hashlib
from dataclasses import dataclass


def h(*parts):
    m = hashlib.sha256()
    for p in parts:
        m.update(repr(p).encode())
        m.update(b"\x1f")
    return m.hexdigest()[:16]


@dataclass
class Fingerprint:
    fp: str
    strength: float
    kind: str  # "ble" | "wifi" | "tracker"
    label: str = ""


# ---- BLE -------------------------------------------------------------------

APPLE = 0x004C
_BASE = "-0000-1000-8000-00805f9b34fb"
# Non-exhaustive list of 16-bit service UUIDs used by consumer trackers.
TRACKER_UUIDS = {
    "feed": "Tile tracker",
    "fd84": "Tile tracker",
    "fd5a": "Samsung SmartTag",
    "fe33": "Chipolo tracker",
}


def short_uuid(u):
    u = u.lower()
    return u[4:8] if u.startswith("0000") and u.endswith(_BASE) else u


def address_class(addr, addr_type=None):
    """public | static (stable random) | rpa/nrpa (rotating random)."""
    if addr_type == "public":
        return "public"
    top = int(addr.split(":")[0], 16) >> 6
    return {3: "static", 1: "rpa", 0: "nrpa"}.get(top, "rpa")


def detect_tracker(manufacturer_data, service_uuids, service_data):
    apple = manufacturer_data.get(APPLE)
    if apple and apple[:1] == b"\x12":
        return "Apple Find My accessory (AirTag or similar)"
    for u in list(service_uuids) + list(service_data):
        name = TRACKER_UUIDS.get(short_uuid(u))
        if name:
            return name
    return None


def ble_fingerprint(addr, addr_type, name, manufacturer_data, service_uuids,
                    service_data=None, tx_power=None):
    service_data = service_data or {}
    cls = address_class(addr, addr_type)
    tracker = detect_tracker(manufacturer_data, service_uuids, service_data)

    if tracker:
        # Tracker addresses rotate slowly (15 min to 24 h); the address is the
        # best handle for "is this thing travelling with me right now".
        return Fingerprint("trk:" + h(addr), 0.9, "tracker", tracker)
    if cls in ("public", "static"):
        return Fingerprint("ble:" + h(addr), 1.0 if cls == "public" else 0.9, "ble",
                           name or "")

    # Rotating random address: fall back to model-level traits.
    mfr = []
    for cid, payload in sorted(manufacturer_data.items()):
        # Apple continuity payloads change constantly, keep only type byte.
        mfr.append((cid, payload[:1]) if cid == APPLE else (cid, len(payload)))
    uuids = sorted(short_uuid(u) for u in service_uuids)
    rich = bool(name or uuids or tx_power is not None)
    return Fingerprint(
        "ble~" + h(name, mfr, uuids, tx_power),
        0.6 if rich else 0.2,
        "ble",
        name or "",
    )


# ---- Wi-Fi -----------------------------------------------------------------

def mac_is_random(mac):
    return bool(int(mac.split(":")[0], 16) & 0x02)


def wifi_fingerprint(mac, ie_hash, ssid):
    if not mac_is_random(mac):
        return Fingerprint("wifi:" + h(mac), 1.0, "wifi", "")
    if ssid:
        # Directed probe for a specific network + exact capability layout.
        return Fingerprint("wifi~" + h(ie_hash, ssid), 0.6, "wifi", "probes:" + ssid[:24])
    return Fingerprint("wifi~" + h(ie_hash), 0.25, "wifi", "")


# ---- Wi-Fi access points (seen by phones, which cannot capture probe requests) ----

def ap_fingerprint(bssid, ssid):
    """An AP's BSSID is stable while it is up. Seen at several places it is a
    mobile hotspot / travel router moving with someone."""
    strength = 0.8 if mac_is_random(bssid) else 1.0
    return Fingerprint("ap:" + h(bssid.lower()), strength, "ap",
                       ("AP: " + ssid[:24]) if ssid else "AP: hidden network")
