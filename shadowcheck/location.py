"""Where am I? Manual label, gpsd, or named places from a JSON file."""
import json
import math
import socket
import threading

GRID = 0.0015  # ~165 m cells for unnamed GPS places


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


class Locator:
    """places_file: [{"name": "Office", "lat": .., "lon": .., "radius_m": 150}, ...]"""

    def __init__(self, manual=None, use_gpsd=False, places_file=None):
        self.manual = manual
        self.fix = None  # (lat, lon)
        self.places = json.load(open(places_file)) if places_file else []
        if use_gpsd:
            threading.Thread(target=self._gpsd, daemon=True).start()

    def _gpsd(self):
        while True:
            try:
                s = socket.create_connection(("127.0.0.1", 2947), timeout=10)
                s.sendall(b'?WATCH={"enable":true,"json":true}\n')
                for line in s.makefile():
                    try:
                        m = json.loads(line)
                    except ValueError:
                        continue
                    if m.get("class") == "TPV" and "lat" in m and "lon" in m:
                        self.fix = (m["lat"], m["lon"])
            except OSError:
                import time
                time.sleep(5)

    def current(self):
        """Returns (place, lat, lon)."""
        if self.manual:
            return self.manual, None, None
        if not self.fix:
            return "unknown", None, None
        lat, lon = self.fix
        for p in self.places:
            if haversine_m(lat, lon, p["lat"], p["lon"]) <= p.get("radius_m", 150):
                return p["name"], lat, lon
        return f"gps:{round(lat / GRID)}:{round(lon / GRID)}", lat, lon
