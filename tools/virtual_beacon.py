#!/usr/bin/env python3
"""Advertise a fake tracker from the Android emulator's virtual Bluetooth controller.

The emulator's netsimd/Rootcanal accepts extra virtual controllers over HCI-on-TCP
(default 127.0.0.1:6402). This connects as one and advertises a BLE packet that looks
like a consumer tracker, so the Android app's real BLE scanner has something to find.

    python tools/virtual_beacon.py --kind airtag          # Apple Find My style
    python tools/virtual_beacon.py --kind tile            # Tile style (service 0xFEED)
    python tools/virtual_beacon.py --kind watch --name Watch   # ordinary named device

Advertising stops when this process exits. Dev/test tool only.
"""
import argparse
import socket
import struct
import time

OP_RESET = 0x0C03
OP_LE_SET_RANDOM_ADDR = 0x2005
OP_LE_SET_ADV_PARAMS = 0x2006
OP_LE_SET_ADV_DATA = 0x2008
OP_LE_SET_ADV_ENABLE = 0x200A


def adv_payload(kind, name):
    if kind == "airtag":
        # Manufacturer data, Apple (0x004C), type 0x12 (offline finding), length 0x19
        body = bytes([0x12, 0x19, 0x10]) + bytes(range(1, 23)) + bytes([0x00, 0x00])
        return bytes([len(body) + 3, 0xFF, 0x4C, 0x00]) + body
    if kind == "tile":
        svc = bytes([0xED, 0xFE]) + bytes(range(1, 9))   # 16-bit UUID 0xFEED + service data
        return bytes([len(svc) + 1, 0x16]) + svc
    n = (name or "Watch").encode()[:20]
    return bytes([len(n) + 1, 0x09]) + n                  # complete local name


class Controller:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=10)

    def cmd(self, opcode, params=b""):
        self.s.sendall(b"\x01" + struct.pack("<HB", opcode, len(params)) + params)
        while True:                                        # wait for the matching Command Complete
            ev = self.s.recv(256)
            if ev[:2] == b"\x04\x0e" and struct.unpack("<H", ev[4:6])[0] == opcode:
                if ev[6] != 0:
                    raise RuntimeError(f"HCI 0x{opcode:04x} failed, status 0x{ev[6]:02x}")
                return ev


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["airtag", "tile", "watch"], default="airtag")
    ap.add_argument("--addr", default="5A:11:22:33:44:55", help="random address (top bits 01 = rotating-style)")
    ap.add_argument("--name", default="Watch")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6402)
    ap.add_argument("--duration", type=int, default=0, help="seconds; 0 = until Ctrl-C")
    a = ap.parse_args()

    c = Controller(a.host, a.port)
    c.cmd(OP_RESET)
    c.cmd(OP_LE_SET_RANDOM_ADDR, bytes(int(x, 16) for x in reversed(a.addr.split(":"))))
    # 100 ms interval, ADV_NONCONN_IND, own address = random, all 3 channels, no filter
    c.cmd(OP_LE_SET_ADV_PARAMS, struct.pack("<HHBBB6sBB", 160, 160, 0x03, 0x01, 0x00, bytes(6), 0x07, 0x00))
    data = adv_payload(a.kind, a.name)
    c.cmd(OP_LE_SET_ADV_DATA, bytes([len(data)]) + data.ljust(31, b"\x00"))
    c.cmd(OP_LE_SET_ADV_ENABLE, b"\x01")
    print(f"advertising {a.kind} as {a.addr} ({data.hex()})", flush=True)
    try:
        t0 = time.time()
        while not a.duration or time.time() - t0 < a.duration:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
