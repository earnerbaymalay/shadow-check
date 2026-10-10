"""Passive Wi-Fi probe-request capture over a raw AF_PACKET socket.

Needs an interface in monitor mode and CAP_NET_RAW (root). Only 802.11
management probe requests are read, and only the transmitter address, signal
level, SSID and information-element layout are kept. No payload or data frames.
"""
import socket
import struct
import subprocess
import threading
import time

from .fingerprint import h, wifi_fingerprint

DEFAULT_CHANNELS = [1, 6, 11, 36, 40, 44, 48, 149, 153, 157, 161]


def parse_radiotap(buf):
    """Return (header_len, signal_dbm or None). Handles fields 0..5 only."""
    if len(buf) < 8:
        return None, None
    _ver, _pad, rt_len, present = struct.unpack_from("<BBHI", buf, 0)
    if rt_len > len(buf):
        return None, None
    off = 8
    p = present
    while p & 0x80000000:  # extended present words
        p = struct.unpack_from("<I", buf, off)[0]
        off += 4
    sizes = [(8, 8), (1, 1), (1, 1), (4, 2), (2, 2), (1, 1)]  # (size, align) bits 0-5
    signal = None
    for bit, (size, align) in enumerate(sizes):
        if not present & (1 << bit):
            continue
        off = (off + align - 1) & ~(align - 1)
        if bit == 5:
            signal = struct.unpack_from("<b", buf, off)[0]
        off += size
    return rt_len, signal


def parse_ies(body):
    ies = []
    i = 0
    while i + 2 <= len(body):
        tid, ln = body[i], body[i + 1]
        if i + 2 + ln > len(body):
            break
        ies.append((tid, bytes(body[i + 2:i + 2 + ln])))
        i += 2 + ln
    return ies


def parse_probe_request(buf):
    """Parse a radiotap-prefixed frame. Returns (mac, rssi, ssid, ie_hash) or None."""
    rt_len, rssi = parse_radiotap(buf)
    if rt_len is None:
        return None
    f = buf[rt_len:]
    if len(f) < 24:
        return None
    fc = f[0]
    ftype, subtype = (fc >> 2) & 3, (fc >> 4) & 0xF
    if ftype != 0 or subtype != 4:  # management / probe request
        return None
    mac = ":".join(f"{b:02x}" for b in f[10:16])
    ies = parse_ies(f[24:])
    ssid = ""
    layout = []
    for tid, data in ies:
        if tid == 0:
            ssid = data.decode("utf-8", "replace")
            continue
        if tid == 221:  # vendor: keep the OUI + type only (cookies can vary)
            layout.append((tid, data[:4]))
        elif tid in (1, 50, 45, 127, 191, 255):  # rates, HT, ext-cap, VHT, HE
            layout.append((tid, data))
        else:
            layout.append((tid, len(data)))
    return mac, rssi, ssid, h(layout)


class WifiSniffer(threading.Thread):
    def __init__(self, iface, recorder, channels=None, hop_interval=0.4):
        super().__init__(daemon=True)
        self.iface, self.rec = iface, recorder
        self.channels = channels or DEFAULT_CHANNELS
        self.hop_interval = hop_interval
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def _hop(self):
        i = 0
        while not self._halt.is_set():
            ch = self.channels[i % len(self.channels)]
            subprocess.run(["iw", "dev", self.iface, "set", "channel", str(ch)],
                           capture_output=True)
            i += 1
            time.sleep(self.hop_interval)

    def run(self):
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
        s.bind((self.iface, 0))
        s.settimeout(1.0)
        threading.Thread(target=self._hop, daemon=True).start()
        while not self._halt.is_set():
            try:
                buf = s.recv(4096)
            except socket.timeout:
                continue
            r = parse_probe_request(buf)
            if r:
                mac, rssi, ssid, ie_hash = r
                fp = wifi_fingerprint(mac, ie_hash, ssid)
                self.rec.record(fp, rssi)
        s.close()
