import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

from .engine import analyze
from .location import Locator
from .recorder import Recorder
from .report import DEFAULT_REPORT, write_report
from .store import Store

DEFAULT_DB = os.path.expanduser("~/.local/share/shadowcheck/shadowcheck.db")


def parse_age(s):
    units = {"m": 60, "h": 3600, "d": 86400}
    return int(s[:-1]) * units[s[-1]] if s[-1] in units else int(s)


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def print_findings(findings, as_json=False):
    if as_json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
        return
    if not findings:
        print("No recurring unknown devices above threshold.")
        return
    for f in findings:
        print(f"[{f.level}] score {f.score:<5} {f.kind:<7} {f.fp}  {f.label}")
        print(f"        places: {', '.join(f.places)}")
        print(f"        {fmt_ts(f.first)} -> {fmt_ts(f.last)}  ({f.encounters} encounters)")
        for r in f.reasons:
            print(f"        - {r}")


def notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", "critical", title, body], check=False)


async def run_scan(args, store):
    loc = Locator(args.place, args.gpsd, args.places_file)
    rec = Recorder(store, loc)
    stop = asyncio.Event()
    tasks, sniffer = [], None

    if args.wifi:
        from .wifi import WifiSniffer
        sniffer = WifiSniffer(args.wifi, rec)
        sniffer.start()
        print(f"Wi-Fi: capturing probe requests on {args.wifi}")
    if not args.no_ble:
        from .ble import scan
        tasks.append(asyncio.create_task(scan(rec, stop)))
        print("BLE: scanning")
    if not tasks and not sniffer:
        sys.exit("Nothing to scan: enable BLE and/or pass --wifi IFACE")

    alerted = {}
    sources = ",".join(x for x, on in (("ble", not args.no_ble), ("wifi", bool(args.wifi))) if on)
    sid = store.session_start(args.place or "gps", sources)
    started = time.time()

    def refresh_report(final=False):
        store.session_update(sid, rec.count)
        if args.report_file:
            try:
                write_report(store, args.report_file, args.window, None if final else
                             {"place": args.place or "gps", "start": started, "obs": rec.count})
            except OSError as e:
                print(f"report write failed: {e}", file=sys.stderr)

    refresh_report()
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    except (NotImplementedError, RuntimeError):
        pass

    async def evaluator():
        while not stop.is_set():
            await asyncio.sleep(args.eval_every)
            refresh_report()
            rows = store.since(time.time() - args.window)
            for f in analyze(rows, store.allowed()):
                if alerted.get(f.fp) == f.level or (alerted.get(f.fp) == "HIGH"):
                    continue
                alerted[f.fp] = f.level
                print(f"\n!! {f.level} {f.kind} {f.fp} {f.label}: {'; '.join(f.reasons)}")
                if args.notify:
                    notify(f"Shadow Check: {f.level}", f"{f.kind} {f.label} {'; '.join(f.reasons)}")

    tasks.append(asyncio.create_task(evaluator()))
    start = time.time()
    try:
        while not stop.is_set() and not (args.duration and time.time() - start >= args.duration):
            await asyncio.sleep(1)
            if int(time.time() - start) % 30 == 0:
                print(f"  {rec.count} observations stored", end="\r", flush=True)
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        if sniffer:
            sniffer.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        refresh_report(final=True)
    print(f"\nDone. {rec.count} observations stored.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="shadowcheck", description=__doc__)
    p.add_argument("--db", default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="collect and watch for recurring devices")
    s.add_argument("--place", help="manual place label (e.g. Office); overrides GPS")
    s.add_argument("--gpsd", action="store_true", help="use gpsd for location")
    s.add_argument("--places-file", help="JSON list of named places for GPS")
    s.add_argument("--wifi", metavar="IFACE", help="monitor-mode interface (needs root)")
    s.add_argument("--no-ble", action="store_true")
    s.add_argument("--duration", type=parse_age, default=0, help="seconds, or 30m/2h; 0 = until Ctrl-C")
    s.add_argument("--window", type=parse_age, default="7d", help="analysis window")
    s.add_argument("--eval-every", type=parse_age, default=60)
    s.add_argument("--retention", type=parse_age, default="14d", help="delete older data at start")
    s.add_argument("--report-file", default=DEFAULT_REPORT,
                   help="HTML report rewritten every scan tick (default: Desktop)")
    s.add_argument("--no-report", action="store_true")
    s.add_argument("--notify", action="store_true", help="desktop notification on alerts")

    r = sub.add_parser("report", help="analyze stored observations")
    r.add_argument("--since", type=parse_age, default="7d")
    r.add_argument("--json", action="store_true")
    r.add_argument("--html", nargs="?", const=DEFAULT_REPORT, metavar="PATH",
                   help="write the HTML report now (default: Desktop)")

    a = sub.add_parser("allow", help="allowlist trusted devices")
    a.add_argument("fps", nargs="*", help="fingerprints to allow")
    a.add_argument("--seen-last", type=parse_age, help="allow everything seen in this window")
    a.add_argument("--note", default="")

    sub.add_parser("list", help="fingerprints seen in last 24h").add_argument(
        "--since", type=parse_age, default="1d")

    d = sub.add_parser("dashboard", help="local web dashboard")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--open", action="store_true", help="open in browser")
    d.add_argument("--host", default="127.0.0.1",
                   help="bind address; non-loopback (e.g. a Tailscale IP or 0.0.0.0) enables "
                        "LAN mode with password login")

    pg = sub.add_parser("purge", help="delete old observations")
    pg.add_argument("--older-than", type=parse_age, default="14d")

    args = p.parse_args(argv)
    store = Store(args.db)

    if args.cmd == "scan":
        if args.no_report:
            args.report_file = None
        store.purge(time.time() - args.retention)
        try:
            asyncio.run(run_scan(args, store))
        except KeyboardInterrupt:
            print("\nStopped.")
    elif args.cmd == "report" and args.html:
        write_report(store, args.html, args.since)
        print(f"Report written: {args.html}")
    elif args.cmd == "report":
        rows = store.since(time.time() - args.since)
        print_findings(analyze(rows, store.allowed()), args.json)
    elif args.cmd == "allow":
        fps = list(args.fps)
        if args.seen_last:
            fps += [fp for fp, _ in store.fingerprints_since(time.time() - args.seen_last)]
        store.allow(fps, args.note)
        print(f"Allowlisted {len(fps)} fingerprint(s).")
    elif args.cmd == "list":
        allowed = store.allowed()
        for fp, label in store.fingerprints_since(time.time() - args.since):
            print(f"{'*' if fp in allowed else ' '} {fp}  {label or ''}")
    elif args.cmd == "dashboard":
        from .dashboard import serve
        serve(store, args.db, args.port, args.open, args.host)
    elif args.cmd == "purge":
        print(f"Deleted {store.purge(time.time() - args.older_than)} observations.")
