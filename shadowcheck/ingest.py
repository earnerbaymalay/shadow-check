"""Accepts raw BLE advertisements from remote sensors (the Android app).

Remote sensors send raw advertisement fields; fingerprints are computed here with
the same code the laptop scanner uses, so one device gets one identity everywhere.
"""
import re
import time

from .fingerprint import ap_fingerprint, ble_fingerprint

MAX_BATCH = 500
MAX_AGE_S = 86400  # a phone that was offline may flush old sightings
ADDR = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HEX = re.compile(r"^([0-9A-Fa-f]{2}){0,62}$")
UUID = re.compile(r"^[0-9A-Fa-f-]{4,36}$")


def clean(s, n):
    return " ".join(str(s or "").split())[:n]


def _one(o, now):
    addr = o.get("addr", "")
    if not ADDR.match(addr):
        raise ValueError("bad addr")
    rssi = o.get("rssi")
    if not isinstance(rssi, int) or not -127 <= rssi <= 20:
        raise ValueError("bad rssi")
    ts = o.get("ts")
    if not isinstance(ts, (int, float)) or not now - MAX_AGE_S <= ts <= now + 60:
        ts = now
    mfr = {}
    for k, v in (o.get("mfr") or {}).items():
        if not (str(k).isdigit() and 0 <= int(k) <= 0xFFFF and HEX.match(str(v))):
            raise ValueError("bad mfr")
        mfr[int(k)] = bytes.fromhex(v)
    uuids = [u.lower() for u in (o.get("uuids") or [])]
    svc = {}
    for k, v in (o.get("svc") or {}).items():
        if not (UUID.match(str(k)) and HEX.match(str(v))):
            raise ValueError("bad svc")
        svc[str(k).lower()] = bytes.fromhex(v)
    if not all(UUID.match(u) for u in uuids):
        raise ValueError("bad uuid")
    tx = o.get("tx")
    if tx is not None and not isinstance(tx, int):
        raise ValueError("bad tx")
    name = clean(o.get("name"), 32) or None
    fp = ble_fingerprint(addr.upper(), None, name, mfr, uuids, svc, tx)
    return ts, fp, rssi


def _ap(o, now):
    bssid = o.get("bssid", "")
    if not ADDR.match(bssid):
        raise ValueError("bad bssid")
    rssi = o.get("rssi")
    if not isinstance(rssi, int) or not -127 <= rssi <= 0:
        raise ValueError("bad rssi")
    ts = o.get("ts")
    if not isinstance(ts, (int, float)) or not now - MAX_AGE_S <= ts <= now + 60:
        ts = now
    if bssid.lower() in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        raise ValueError("bad bssid")
    return ts, ap_fingerprint(bssid, clean(o.get("ssid"), 32)), rssi


def ingest(store, payload, now=None):
    """Returns {"accepted": n, "rejected": n}. Never raises on bad observations."""
    now = now or time.time()
    device = clean(payload.get("device"), 24) or "remote"
    place = clean(payload.get("place"), 40)
    obs = payload.get("observations", [])
    wifi = payload.get("wifi", [])
    if (not place or not isinstance(obs, list) or not isinstance(wifi, list)
            or len(obs) + len(wifi) > MAX_BATCH):
        raise ValueError("place and observations/wifi lists (<=%d total) required" % MAX_BATCH)
    ok = bad = 0
    for items, parse in ((obs, _one), (wifi, _ap)):
        for o in items:
            try:
                ts, fp, rssi = parse(o, now)
            except (ValueError, AttributeError, TypeError):
                bad += 1
                continue
            store.add(ts, fp.fp, fp.kind, fp.strength, rssi, place, None, None, fp.label, src=device)
            ok += 1
    return {"accepted": ok, "rejected": bad}
