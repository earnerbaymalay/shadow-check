"""Throttled bridge from collectors to the store."""
import threading
import time


class Recorder:
    def __init__(self, store, locator, throttle_s=5.0):
        self.store, self.locator, self.throttle = store, locator, throttle_s
        self._last = {}
        self._lock = threading.Lock()
        self.count = 0

    def record(self, fp, rssi):
        now = time.time()
        with self._lock:
            if now - self._last.get(fp.fp, 0) < self.throttle:
                return
            self._last[fp.fp] = now
            self.count += 1
        place, lat, lon = self.locator.current()
        self.store.add(now, fp.fp, fp.kind, fp.strength, rssi, place, lat, lon, fp.label)
