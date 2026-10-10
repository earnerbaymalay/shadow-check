"""Self-contained HTML report, rewritten after every scan tick. No JavaScript."""
import html
import os
import tempfile
import time
from datetime import datetime

from .engine import analyze

KIND = {"ble": "Bluetooth", "wifi": "Wi-Fi", "ap": "Wi-Fi AP", "tracker": "Tracker"}
DEFAULT_REPORT = os.path.expanduser("~/Desktop/Shadow Check Report.html")

CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14181f;--mute:#5d6675;--line:#e3e6eb;--high:#c62828;--highbg:#fdecec;
--med:#b26a00;--medbg:#fff3df;--ok:#1b7f45;--okbg:#e6f5ec}
@media (prefers-color-scheme:dark){:root{--bg:#0f1319;--panel:#171c24;--ink:#e8ebf0;--mute:#97a1b2;--line:#27303c;
--high:#ff7b7b;--highbg:#3a1c1f;--med:#f2b254;--medbg:#3a2d17;--ok:#5fcf8c;--okbg:#17301f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:16px}h1{font-size:22px;margin:0}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:24px 0 8px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:8px}
.verdict{font-size:16px;font-weight:650;padding:12px;border-radius:10px}
.v-ok{background:var(--okbg);color:var(--ok)}.v-med{background:var(--medbg);color:var(--med)}.v-high{background:var(--highbg);color:var(--high)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:12px 0}
.n{font-size:22px;font-weight:650}.l,.muted{color:var(--mute);font-size:12px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--mute)}.scroll{overflow-x:auto}.mono{font-family:ui-monospace,monospace;font-size:12px}
.badge{padding:1px 8px;border-radius:99px;font-size:11px;font-weight:650}
.HIGH{background:var(--highbg);color:var(--high)}.MEDIUM{background:var(--medbg);color:var(--med)}
.alert{border-left:4px solid var(--med)}.alert.HIGH{border-left-color:var(--high)}
ul{margin:4px 0 0;padding-left:18px;color:var(--mute)}
"""


def esc(x):
    return html.escape("" if x is None else str(x))


def ts(t):
    return datetime.fromtimestamp(t).strftime("%d %b %Y %H:%M")


def dur(sec):
    sec = int(sec)
    return f"{sec // 3600}h {sec % 3600 // 60}m" if sec >= 3600 else f"{sec // 60}m {sec % 60}s"


def build_html(store, window_s, active=None):
    now = time.time()
    rows = store.since(now - window_s)
    allowed = store.allowed()
    findings = analyze(rows, allowed)
    devices = store.devices(now - window_s)
    level = {f.fp: f.level for f in findings}
    high = sum(f.level == "HIGH" for f in findings)

    if high:
        verdict, vcls = f"{high} HIGH-risk alert(s): review below", "v-high"
    elif findings:
        verdict, vcls = f"{len(findings)} item(s) need a look", "v-med"
    else:
        verdict, vcls = "No recurring unknown devices or following trackers detected", "v-ok"

    scan = (f"Scan active at “{esc(active['place'])}” since {ts(active['start'])} "
            f"({dur(now - active['start'])}, {active['obs']} observations this scan)"
            if active else "No scan currently running")

    o = [f"<!doctype html><html lang=en><head><meta charset=utf-8>"
         f"<meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<meta http-equiv=refresh content=60><title>Shadow Check Report</title>"
         f"<style>{CSS}</style></head><body><div class=wrap>"
         f"<h1>Shadow Check report</h1>"
         f"<div class=muted>Updated {ts(now)} · window: last {window_s // 86400} day(s) · {scan}</div>"
         f"<div class='verdict {vcls}' style='margin-top:12px'>{esc(verdict)}</div>"]
    tiles = [("Observations", len(rows)), ("Devices", len(devices)),
             ("Trackers", sum(d[1] == "tracker" for d in devices)),
             ("Flagged", len(findings)), ("Trusted", len(allowed))]
    o.append("<div class=tiles>" + "".join(
        f"<div class=panel><div class=n>{n}</div><div class=l>{esc(l)}</div></div>" for l, n in tiles) + "</div>")

    o.append("<h2>Alerts</h2>")
    for f in findings:
        o.append(f"<div class='panel alert {f.level}'><span class='badge {f.level}'>{f.level}</span> "
                 f"<strong>{esc(f.label or KIND[f.kind])}</strong> "
                 f"<span class='muted'>{KIND[f.kind]} · score {f.score} · <span class=mono>{esc(f.fp)}</span></span>"
                 f"<div class=muted>{esc(' → '.join(f.places))} · {ts(f.first)} – {ts(f.last)} · "
                 f"{f.encounters} encounters</div><ul>"
                 + "".join(f"<li>{esc(r)}</li>" for r in f.reasons) + "</ul></div>")
    if not findings:
        o.append("<div class='panel muted'>Nothing flagged. Devices are flagged when they appear at "
                 "2+ different places, or a tracker travels with you.</div>")

    trk = [d for d in devices if d[1] == "tracker" and d[0] not in allowed]
    o.append("<h2>Trackers nearby</h2>")
    if trk:
        o.append("<div class='panel scroll'><table><tr><th>Fingerprint<th>Type<th>Sightings<th>Places<th>First<th>Last<th>Status</tr>")
        for fp, _k, label, _s, n, first, last, places, _r in trk:
            o.append(f"<tr><td class=mono>{esc(fp)}<td>{esc(label)}<td>{n}<td>{esc(places)}"
                     f"<td>{ts(first)}<td>{ts(last)}<td>{esc(level.get(fp, '—'))}</tr>")
        o.append("</table></div>")
    else:
        o.append("<div class='panel muted'>No unrecognised trackers in range.</div>")

    o.append("<h2>Devices (most recent 40, untrusted)</h2><div class='panel scroll'><table>"
             "<tr><th>Status<th>Type<th>Fingerprint<th>Name<th>Places<th>Sightings<th>Last seen<th>Avg RSSI</tr>")
    shown = [d for d in devices if d[0] not in allowed][:40]
    for fp, kind, label, _s, n, _first, last, places, rssi in shown:
        st = f"<span class='badge {level[fp]}'>{level[fp]}</span>" if fp in level else "—"
        o.append(f"<tr><td>{st}<td>{KIND[kind]}<td class=mono>{esc(fp)}<td>{esc(label)}<td>{esc(places)}"
                 f"<td>{n}<td>{ts(last)}<td>{'' if rssi is None else f'{round(rssi)} dBm'}</tr>")
    o.append("</table></div>")

    o.append("<h2>Scan history</h2><div class='panel scroll'><table>"
             "<tr><th>#<th>Place<th>Started<th>Duration<th>Observations<th>Sources</tr>")
    for sid, start, end, place, obs, sources in store.sessions(20):
        o.append(f"<tr><td>{sid}<td>{esc(place)}<td>{ts(start)}<td>{dur(end - start)}<td>{obs}<td>{esc(sources)}</tr>")
    o.append("</table></div>")
    o.append("<p class=muted>Findings are leads for a human, not proof. Randomised phone addresses "
             "limit what passive scanning can link. Contains anonymous device fingerprints only.</p>"
             "</div></body></html>")
    return "".join(o)


def write_report(store, path, window_s, active=None):
    """Atomic write so a half-written file is never visible."""
    data = build_html(store, window_s, active)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".sc-report-")
    with os.fdopen(fd, "w") as f:
        f.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
