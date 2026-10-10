"""Recurrence engine: which unknown devices keep turning up around the protectee?

Observations are grouped into *encounters* (continuous presence at one place).
A device is suspicious when it has meaningful encounters at several different
places or days, stays physically close, and is not on the allowlist. Trackers
are judged on dwell time and movement instead.
"""
import datetime as dt
from dataclasses import dataclass, field


@dataclass
class Config:
    gap_s: int = 300            # silence longer than this ends an encounter
    min_encounter_s: int = 60   # shorter encounters are passers-by
    min_obs: int = 3
    close_rssi: dict = field(default_factory=lambda: {"ble": -65, "wifi": -60, "tracker": -70})
    high: float = 6.0
    medium: float = 3.0
    tracker_dwell_s: int = 20 * 60


@dataclass
class Finding:
    fp: str
    kind: str
    label: str
    level: str
    score: float
    places: list
    days: list
    encounters: int
    first: float
    last: float
    reasons: list


def _encounters(rows, cfg):
    encs, cur = [], None
    for ts, _fp, _kind, _st, rssi, place, *_ in rows:
        if cur and place == cur["place"] and ts - cur["end"] <= cfg.gap_s:
            cur["end"] = ts
            cur["n"] += 1
            cur["rssi"].append(rssi)
        else:
            cur = {"place": place, "start": ts, "end": ts, "n": 1, "rssi": [rssi]}
            encs.append(cur)
    return encs


def _day(ts):
    return dt.date.fromtimestamp(ts).isoformat()


def analyze(rows, allowed=frozenset(), cfg=None):
    """rows: (ts, fp, kind, strength, rssi, place, lat, lon, label) tuples.
    Returns findings (MEDIUM and above) sorted by score, highest first."""
    cfg = cfg or Config()
    by_fp = {}
    for r in rows:
        if r[1] not in allowed:
            by_fp.setdefault(r[1], []).append(r)

    findings = []
    for fp, rs in by_fp.items():
        rs.sort(key=lambda r: r[0])
        kind = rs[0][2]
        strength = max(r[3] for r in rs)
        label = next((r[8] for r in reversed(rs) if r[8]), "")
        encs = [e for e in _encounters(rs, cfg)
                if e["n"] >= cfg.min_obs and e["end"] - e["start"] >= cfg.min_encounter_s]
        if not encs:
            continue

        places = sorted({e["place"] for e in encs})
        days = sorted({_day(e["start"]) for e in encs})
        close_thr = cfg.close_rssi.get(kind, -65)
        sig = [x for e in encs for x in e["rssi"] if x is not None]
        close_frac = (sum(1 for x in sig if x >= close_thr) / len(sig)) if sig else 0.0
        day_places = {}
        for e in encs:
            day_places.setdefault(_day(e["start"]), set()).add(e["place"])
        same_day_multi = any(len(p) > 1 for p in day_places.values())

        reasons = []
        if kind == "tracker":
            longest = max(e["end"] - e["start"] for e in encs)
            if len(places) >= 2:
                level, score = "HIGH", 10.0
                reasons.append(f"tracker seen at {len(places)} places: moving with you")
            elif longest >= cfg.tracker_dwell_s:
                level, score = "MEDIUM", 5.0
                reasons.append(f"tracker present {longest // 60} min: check bags, vehicle, clothing")
            else:
                continue
        else:
            if len(places) < 2:
                continue  # single-place devices are neighbours, staff, cafe Wi-Fi...
            score = strength * (2.5 * (len(places) - 1) + 0.75 * (len(days) - 1)
                                + 1.5 * close_frac + (0.5 if same_day_multi else 0.0))
            score = round(score, 2)
            level = "HIGH" if score >= cfg.high else "MEDIUM" if score >= cfg.medium else None
            if not level:
                continue
            reasons.append(f"seen at {len(places)} places over {len(days)} day(s)")
            if close_frac >= 0.5:
                reasons.append(f"mostly within close range ({close_frac:.0%} of sightings)")
            if same_day_multi:
                reasons.append("appeared at multiple places on the same day")
            if strength < 0.5:
                reasons.append("weak fingerprint: may be several identical phones")

        findings.append(Finding(fp, kind, label, level, score, places, days, len(encs),
                                rs[0][0], rs[-1][0], reasons))

    findings.sort(key=lambda f: (f.level != "HIGH", -f.score))
    return findings
