"""Local web dashboard. Standard library only; binds to loopback.

Safety model: loopback bind, Host-header check (DNS rebinding), per-run secret
token + JSON content-type on every state-changing request (CSRF), strict CSP
with nonces. All radio-derived strings are rendered with textContent only.
"""
import base64
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import Config, _encounters, analyze
from .ingest import ingest

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "scan.log"
PAGE = (Path(__file__).parent / "dashboard.html").read_text()
KEY_FILE = Path(os.path.expanduser("~/.local/share/shadowcheck/api-key"))


def api_key():
    """Persistent secret shared with remote sensors and used for LAN logins."""
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(24))
    return KEY_FILE.read_text().strip()


def local_urls(port):
    """Addresses this machine is reachable on (LAN / Tailscale), best effort."""
    urls = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True,
                             text=True, timeout=3).stdout
        for line in out.splitlines():
            parts = line.split()
            ip = parts[3].split("/")[0]
            if not ip.startswith("127."):
                urls.append(f"http://{ip}:{port}")
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return urls


# ---- scanner process control ------------------------------------------------

def find_scanners():
    """Running `shadowcheck scan` processes (ours or started from a shell)."""
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            continue
        argv = [a.decode(errors="replace") for a in raw.split(b"\0") if a]
        if "shadowcheck" in argv and "scan" in argv and "-m" in argv:
            place = argv[argv.index("--place") + 1] if "--place" in argv[:-1] else ""
            found.append({"pid": int(pid), "place": place})
    return found


def stop_scanners():
    for s in find_scanners():
        try:
            os.kill(s["pid"], signal.SIGTERM)
        except OSError:
            continue
        for _ in range(30):
            if not os.path.exists(f"/proc/{s['pid']}"):
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(s["pid"], signal.SIGKILL)
            except OSError:
                pass


def start_scanner(db, place):
    LOG.parent.mkdir(exist_ok=True)
    log = open(LOG, "ab")
    subprocess.Popen(
        [sys.executable, "-u", "-m", "shadowcheck", "--db", db, "scan",
         "--place", place, "--notify"],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )


def clean_place(s):
    s = " ".join(str(s).split())[:40]
    return s if s and not s.startswith("-") else None


# ---- HTTP -------------------------------------------------------------------

def make_handler(store, db_path, port, token, key, lan):
    ok_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "ShadowCheck"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj))

        def _key_ok(self):
            """Bearer <key>, or HTTP Basic with the key as password."""
            a = self.headers.get("Authorization", "")
            cand = ""
            if a.startswith("Bearer "):
                cand = a[7:]
            elif a.startswith("Basic "):
                try:
                    cand = base64.b64decode(a[6:]).decode().partition(":")[2]
                except ValueError:
                    pass
            return secrets.compare_digest(cand.encode(), key.encode())

        def _host_ok(self):
            if lan:  # reachable by others: authenticate instead of host-pinning
                if not self._key_ok():
                    self._send(401, '{"error":"auth required"}',
                               extra={"WWW-Authenticate": 'Basic realm="Shadow Check"'})
                    return False
                return True
            if self.headers.get("Host") not in ok_hosts:
                self._send(403, '{"error":"bad host"}')
                return False
            return True

        def do_GET(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            since_s = int(q.get("since", ["604800"])[0])
            since = time.time() - max(60, min(since_s, 14 * 86400))
            if u.path == "/":
                nonce = secrets.token_urlsafe(16)
                html = PAGE.replace("__NONCE__", nonce).replace("__TOKEN__", token)
                csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; "
                       f"style-src 'nonce-{nonce}'; connect-src 'self'; "
                       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self._send(200, html, "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
            elif u.path == "/api/state":
                self._json(self.state(since))
            elif u.path == "/api/pairing":
                self._json({"key": key, "urls": local_urls(port), "lan": lan})
            elif u.path == "/api/device":
                self._json(self.device(q.get("fp", [""])[0], since))
            else:
                self._send(404, '{"error":"not found"}')

        def do_POST(self):
            if urlparse(self.path).path == "/api/ingest":
                if not self._key_ok():
                    return self._send(401, '{"error":"bad key"}')
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._send(415, '{"error":"json required"}')
                try:
                    n = min(int(self.headers.get("Content-Length", 0)), 512 * 1024)
                    return self._json(ingest(store, json.loads(self.rfile.read(n) or b"{}")))
                except (ValueError, AttributeError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if not self._host_ok():
                return
            if (self.headers.get("X-Token") != token
                    or "application/json" not in (self.headers.get("Content-Type") or "")):
                return self._send(403, '{"error":"forbidden"}')
            try:
                n = min(int(self.headers.get("Content-Length", 0)), 4096)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, '{"error":"bad json"}')
            path = urlparse(self.path).path

            if path in ("/api/allow", "/api/unallow"):
                fp = str(body.get("fp", ""))[:64]
                if not fp:
                    return self._send(400, '{"error":"fp required"}')
                if path == "/api/allow":
                    store.allow([fp], str(body.get("note", ""))[:80])
                else:
                    store.unallow(fp)
                return self._json({"ok": True})

            if path == "/api/scanner":
                action = body.get("action")
                if action == "stop":
                    stop_scanners()
                elif action in ("start", "restart"):
                    place = clean_place(body.get("place", ""))
                    if not place:
                        return self._send(400, '{"error":"place required"}')
                    stop_scanners()
                    start_scanner(db_path, place)
                    time.sleep(1.5)
                else:
                    return self._send(400, '{"error":"bad action"}')
                return self._json({"ok": True, "scanners": find_scanners()})
            self._send(404, '{"error":"not found"}')

        # -- data --
        def state(self, since):
            allowed = store.allowed()
            rows = store.since(since)
            findings = analyze(rows, allowed)
            level = {f.fp: f.level for f in findings}
            devs = []
            for fp, kind, label, strength, n, first, last, places, rssi in store.devices(since):
                devs.append({
                    "fp": fp, "kind": kind, "label": label or "", "strength": strength,
                    "count": n, "first": first, "last": last,
                    "places": (places or "").split(","),
                    "rssi": None if rssi is None else round(rssi),
                    "allowed": fp in allowed, "level": level.get(fp),
                })
            return {
                "now": time.time(),
                "scanners": find_scanners(),
                "stats": {"observations": len(rows), "devices": len(devs),
                          "trackers": sum(d["kind"] == "tracker" for d in devs),
                          "flagged": len(findings), "allowlisted": len(allowed)},
                "findings": [f.__dict__ for f in findings],
                "devices": devs,
            }

        def device(self, fp, since):
            rows = store.fp_rows(fp, since)
            encs = _encounters(rows, Config())
            return {"fp": fp, "encounters": [
                {"place": e["place"], "start": e["start"], "end": e["end"], "n": e["n"],
                 "rssi": max((x for x in e["rssi"] if x is not None), default=None)}
                for e in encs]}

    return H


def serve(store, db_path, port=8765, open_browser=False, host="127.0.0.1"):
    token = secrets.token_urlsafe(24)
    key = api_key()
    lan = host not in ("127.0.0.1", "localhost", "::1")
    srv = ThreadingHTTPServer((host, port), make_handler(store, db_path, port, token, key, lan))
    url = f"http://127.0.0.1:{port}/"
    print(f"Shadow Check dashboard: {url}   (Ctrl-C to stop; scanner keeps running)")
    if lan:
        print(f"LAN mode on {host}:{port}. Login password / sensor key: see {KEY_FILE}")
        print("Traffic is plain HTTP: use Tailscale/VPN or a trusted network.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
