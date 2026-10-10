"""SQLite observation store. Holds only anonymous fingerprints, never traffic content."""
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS obs(
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    fp TEXT NOT NULL,
    kind TEXT NOT NULL,
    strength REAL NOT NULL,
    rssi INTEGER,
    place TEXT NOT NULL,
    lat REAL,
    lon REAL,
    label TEXT
);
CREATE INDEX IF NOT EXISTS obs_fp ON obs(fp, ts);
CREATE INDEX IF NOT EXISTS obs_ts ON obs(ts);
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY, start REAL NOT NULL, end REAL NOT NULL,
    place TEXT NOT NULL, obs INTEGER NOT NULL DEFAULT 0, sources TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS allow(fp TEXT PRIMARY KEY, note TEXT, added REAL);
"""

COLS = "ts, fp, kind, strength, rssi, place, lat, lon, label"


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        new = not os.path.exists(path)
        self._db = sqlite3.connect(path, check_same_thread=False)
        if new:
            os.chmod(path, 0o600)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            if "src" not in {r[1] for r in self._db.execute("PRAGMA table_info(obs)")}:
                self._db.execute("ALTER TABLE obs ADD COLUMN src TEXT NOT NULL DEFAULT ''")

    def add(self, ts, fp, kind, strength, rssi, place, lat, lon, label, src=""):
        with self._lock:
            self._db.execute(
                f"INSERT INTO obs({COLS}, src) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, fp, kind, strength, rssi, place, lat, lon, label, src),
            )
            self._db.commit()

    def since(self, ts):
        with self._lock:
            return self._db.execute(
                f"SELECT {COLS} FROM obs WHERE ts >= ? ORDER BY ts", (ts,)
            ).fetchall()

    def fingerprints_since(self, ts):
        with self._lock:
            return self._db.execute(
                "SELECT fp, MAX(label) FROM obs WHERE ts >= ? GROUP BY fp", (ts,)
            ).fetchall()

    def allowed(self):
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT fp FROM allow")}

    def allow(self, fps, note=""):
        now = time.time()
        with self._lock:
            self._db.executemany(
                "INSERT OR REPLACE INTO allow(fp, note, added) VALUES(?,?,?)",
                [(fp, note, now) for fp in fps],
            )
            self._db.commit()

    def purge(self, older_than_ts):
        with self._lock:
            n = self._db.execute("DELETE FROM obs WHERE ts < ?", (older_than_ts,)).rowcount
            self._db.commit()
            return n

    def unallow(self, fp):
        with self._lock:
            self._db.execute("DELETE FROM allow WHERE fp = ?", (fp,))
            self._db.commit()

    def fp_rows(self, fp, since):
        with self._lock:
            return self._db.execute(
                f"SELECT {COLS} FROM obs WHERE fp = ? AND ts >= ? ORDER BY ts", (fp, since)
            ).fetchall()

    def devices(self, since):
        """One summary row per fingerprint seen since `since`."""
        with self._lock:
            return self._db.execute(
                "SELECT fp, kind, MAX(label), MAX(strength), COUNT(*), MIN(ts), MAX(ts),"
                " GROUP_CONCAT(DISTINCT place), AVG(rssi) FROM obs WHERE ts >= ?"
                " GROUP BY fp ORDER BY MAX(ts) DESC", (since,)
            ).fetchall()

    def session_start(self, place, sources):
        now = time.time()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO sessions(start, end, place, obs, sources) VALUES(?,?,?,0,?)",
                (now, now, place, sources))
            self._db.commit()
            return cur.lastrowid

    def session_update(self, sid, obs):
        with self._lock:
            self._db.execute("UPDATE sessions SET end = ?, obs = ? WHERE id = ?",
                             (time.time(), obs, sid))
            self._db.commit()

    def sessions(self, limit=20):
        with self._lock:
            return self._db.execute(
                "SELECT id, start, end, place, obs, sources FROM sessions"
                " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
