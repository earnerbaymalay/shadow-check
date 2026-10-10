import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from shadowcheck import dashboard
from shadowcheck.ingest import ingest
from shadowcheck.store import Store

NOW = 1_750_000_000.0
AIRTAG = {"addr": "5A:11:22:33:44:55", "rssi": -60, "mfr": {"76": "1219" + "00" * 24}}


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


def test_ingest_tracker_and_plain_device(store):
    r = ingest(store, {"device": "pixel", "place": "Gym", "observations": [
        dict(AIRTAG, ts=NOW),
        {"addr": "C1:00:00:00:00:01", "rssi": -50, "name": "Watch", "ts": NOW}]}, now=NOW)
    assert r == {"accepted": 2, "rejected": 0}
    rows = store.since(0)
    assert {x[2] for x in rows} == {"tracker", "ble"}
    assert all(x[5] == "Gym" for x in rows)


def test_bad_observations_rejected_not_fatal(store):
    bad = [{"addr": "nope", "rssi": -50}, {"addr": "C1:00:00:00:00:01", "rssi": 999},
           {"addr": "C1:00:00:00:00:01", "rssi": -50, "mfr": {"x": "zz"}},
           {"addr": "C1:00:00:00:00:01", "rssi": -50, "uuids": ["<script>"]}, "junk", None]
    ok = {"addr": "C1:00:00:00:00:02", "rssi": -50}
    assert ingest(store, {"place": "A", "observations": bad + [ok]}, now=NOW) == {"accepted": 1, "rejected": 6}


def test_requires_place_and_batch_limit(store):
    with pytest.raises(ValueError):
        ingest(store, {"observations": []})
    with pytest.raises(ValueError):
        ingest(store, {"place": "A", "observations": [ok_obs() for _ in range(501)]})


def ok_obs():
    return {"addr": "C1:00:00:00:00:02", "rssi": -50}


def test_same_device_same_fingerprint_as_laptop(store):
    from shadowcheck.fingerprint import ble_fingerprint
    ingest(store, {"place": "A", "observations": [
        {"addr": "A0:51:0B:AF:B8:F0", "rssi": -40, "name": "Pixel 8", "ts": NOW}]}, now=NOW)
    fp = ble_fingerprint("A0:51:0B:AF:B8:F0", None, "Pixel 8", {}, [], {}, None)
    assert store.since(0)[0][1] == fp.fp


def test_ingest_over_http_requires_key(store, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "KEY_FILE", tmp_path / "key")
    key = dashboard.api_key()
    assert oct((tmp_path / "key").stat().st_mode & 0o777) == "0o600"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.make_handler(store, "x", 0, "tok", key, False))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/ingest"
    body = json.dumps({"place": "Gym", "observations": [dict(AIRTAG)]}).encode()

    def post(auth):
        h = {"Content-Type": "application/json"}
        if auth:
            h["Authorization"] = auth
        try:
            return urllib.request.urlopen(urllib.request.Request(url, body, h)).status
        except urllib.error.HTTPError as e:
            return e.code

    assert post(None) == 401
    assert post("Bearer wrong") == 401
    assert post(f"Bearer {key}") == 200
    assert len(store.since(0)) == 1
    srv.shutdown()


def test_lan_mode_requires_login_for_pages(store, tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "KEY_FILE", tmp_path / "key")
    key = dashboard.api_key()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.make_handler(store, "x", 0, "tok", key, True))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/state"
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(url)
    assert e.value.code == 401
    import base64
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + base64.b64encode(f"u:{key}".encode()).decode()})
    assert urllib.request.urlopen(req).status == 200
    srv.shutdown()
