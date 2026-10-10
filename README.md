# Shadow Check

**Passive counter-surveillance for people who may be followed or tracked.**
Shadow Check listens for nearby Bluetooth LE (and optionally Wi-Fi probe) traffic,
fingerprints devices **without reading phone numbers, names of people or message
content**, and flags unknown devices that keep turning up across different places and
days, plus hidden trackers (AirTag, Tile, SmartTag, Chipolo) that travel with you.

It is built for protection details, journalists, activists, and anyone with stalking
concerns. It is a **defensive** tool: it never connects to other devices, never decodes
traffic, and never tries to identify who owns a device.

```
 Linux laptop / Pi                         Android phone (optional sensor)
 ┌──────────────────────────┐              ┌─────────────────────────┐
 │ BLE scanner  Wi-Fi sniffer│              │ Shadow Check app        │
 │        │          │       │              │ BLE scan (foreground)   │
 │        ▼          ▼       │   HTTP       │   │                     │
 │   fingerprints ◄──────────┼──────────────┼───┘ raw adverts, batched│
 │        │      /api/ingest │  (use VPN)   │ ◄── alert notifications │
 │        ▼                  │              └─────────────────────────┘
 │  SQLite ──► recurrence engine ──► alerts, dashboard, HTML report
 └──────────────────────────┘
```

## Features
- **Recurrence engine:** groups sightings into encounters per place; flags devices seen
  at 2+ places/days, weighted by proximity (RSSI) and fingerprint uniqueness.
- **Tracker detection:** Apple Find My accessories, Tile, Samsung SmartTag, Chipolo.
  HIGH if one moves with you, MEDIUM if one lingers 20+ minutes.
- **Local web dashboard:** live alerts, device table, per-device timeline, trust list,
  scanner start/stop.
- **Living HTML report:** rewritten on every scan tick (default `~/Desktop/Shadow Check
  Report.html`), including a scan-session history.
- **Android app:** turns a phone into a roaming sensor and shows alerts as notifications.
- **Privacy by design:** only anonymous fingerprints are stored (0600 SQLite file),
  auto-purged after 14 days, no cloud, no telemetry.

## Quick start (Linux)
```bash
git clone https://github.com/earnerbaymalay/shadow-check.git && cd shadow-check
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/shadowcheck scan --place Home --notify       # Ctrl-C to stop
```
Needs a Bluetooth adapter and BlueZ. No root required for Bluetooth.

1. **Build a trusted baseline.** Scan while only your own people/devices are around, then
   `shadowcheck allow --seen-last 30m --note household`.
2. **Take it with you.** Run it wherever you go and change `--place` (Home, Gym, Office…),
   or use GPS: `shadowcheck scan --gpsd --places-file places.json`.
3. **Review.** `shadowcheck report`, the dashboard, or the Desktop report.

`places.json`: `[{"name": "Office", "lat": 51.5, "lon": -0.12, "radius_m": 150}]`

### Commands
| Command | Purpose |
|---|---|
| `scan` | collect and watch (`--place`, `--gpsd`, `--wifi IFACE`, `--notify`, `--report-file`) |
| `report` | analyse stored data (`--since 7d`, `--json`, `--html [PATH]`) |
| `dashboard` | local web UI (`--port`, `--open`, `--host`) |
| `allow` / `list` / `purge` | manage trusted devices, list fingerprints, delete old data |

### Dashboard
```bash
.venv/bin/shadowcheck dashboard --open        # http://127.0.0.1:8765/
./install-shortcut.sh                          # optional desktop icon (Linux)
```
Loopback-only by default. State-changing requests need a per-run secret token, the page
has a strict CSP, and radio-derived text (device names, SSIDs) is never rendered as HTML.

### Desktop report
Every scan rewrites `~/Desktop/Shadow Check Report.html` once a minute and when it stops:
verdict, alerts with reasons, trackers nearby, devices, and scan history. Open it in any
browser (it auto-refreshes). Change with `--report-file PATH`, disable with `--no-report`.

### Wi-Fi probe capture (optional)
Needs root and a monitor-mode adapter. Use a **second USB adapter** so your main
connection is untouched:
```bash
sudo ip link set wlan1 down && sudo iw dev wlan1 set type monitor && sudo ip link set wlan1 up
sudo .venv/bin/shadowcheck scan --place Home --wifi wlan1
```
Only 802.11 probe requests are read (transmitter address, signal, SSID, capability layout).
> Status: the frame parser is unit-tested on hand-built frames; it has **not** yet been
> exercised against a live monitor-mode interface.

## Android app
A native Kotlin app in [`android/`](android) (no third-party dependencies, min Android 8.0).
It scans BLE **and Wi-Fi access points** on the phone and uploads them to the dashboard, which computes
fingerprints with the same code as the laptop so one device gets one identity everywhere.
A phone cannot capture other phones' Wi-Fi probe requests, but it can see access points, so a
mobile hotspot or travel router that keeps appearing at your different places is flagged too.
It also polls the dashboard and raises a notification when something is flagged.

**Setup**
1. Open `android/` in **Android Studio** and let it sync (it will offer to upgrade the
   Android Gradle Plugin if your Studio is newer; accept).
2. Run on a phone (USB debugging) or build an APK: *Build ▸ Build APK(s)*.
3. On the computer, start the dashboard reachable by the phone, ideally over
   [Tailscale](https://tailscale.com) or another VPN: `shadowcheck dashboard --host <tailscale-or-LAN-IP>`
4. In the dashboard click **Connect phone** for the address and key; enter them in the app,
   set the place name, and press *Start scanning*.

Full details, permissions and limitations: [`docs/ANDROID.md`](docs/ANDROID.md).

> Status: verified on an Android 17 emulator (Wi-Fi AP scanning, BLE tracker scanning, place
> switching, alerts, screen-off tracker filters, service restart): see
> [`docs/EMULATOR_TEST.md`](docs/EMULATOR_TEST.md). **Not yet tested on a physical phone.**

## Security model
- Dashboard binds to `127.0.0.1` unless you pass `--host`. Non-loopback mode requires a
  login (HTTP Basic, password = API key in `~/.local/share/shadowcheck/api-key`, mode 0600).
- `/api/ingest` always requires the key (Bearer). Input is strictly validated and capped.
- Traffic is **plain HTTP**: use a VPN (Tailscale/WireGuard) or a network you trust.
- The Android key is stored in app-private storage; backups are disabled.

## How detection works
- **Fingerprint:** a real (public/static) MAC when present; otherwise a hash of model
  traits (name, services, capability layout, probed SSIDs). Each carries a *strength*;
  weak ones are discounted since many identical phones share them.
- **Encounter:** continuous presence at one place (≥ 60 s, ≥ 3 sightings).
- **Score:** `strength × (2.5·(places−1) + 0.75·(days−1) + 1.5·closeness + same-day bonus)`.
  HIGH ≥ 6, MEDIUM ≥ 3. Single-place devices are ignored (neighbours, staff, café Wi-Fi).
- **Trackers:** HIGH at 2+ places; MEDIUM if present 20+ min at one place.

## Limits: please read
- Modern phones **randomise addresses**. A determined stalker with a current phone may not
  be linkable. This reliably catches trackers, older devices and careless followers.
- Tracker addresses rotate (15 min to 24 h), so linking works only inside that window.
- Android pauses unfiltered Bluetooth scans when the screen is off, so the app falls back to
  tracker-specific filters then.
- Findings are **leads for a human**, not proof. Crowds create false positives.
- It cannot read, find or infer anyone's phone number. Nothing here can.
- Combine with physical sweeps (car, bags), the phone OS's built-in tracker alerts, and
  professional/police help for real threats.

## Responsible use
Use it to protect yourself or people who have asked you to protect them. Do not use it to
monitor, profile or locate other people. Passive radio listening is legal in many places
but not all; know your local law. Keep retention short and never share raw data.

## Development
```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest      # 30 tests
```
Layout: `shadowcheck/` (engine, fingerprinting, collectors, dashboard, ingest, report),
`tests/`, `android/` (Kotlin app), `tools/` (emulator beacon), `docs/`.

## License
MIT. See [LICENSE](LICENSE).
