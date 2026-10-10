# Testing the Android app on an Android Virtual Device

The emulator has a virtual Wi-Fi access point (`AndroidWifi`) and a virtual Bluetooth LE
controller, so the app's real scanning code runs against real (virtual) radio data. Use a
**throwaway database and key** so test data never mixes with real detections.

## 1. Test server (own DB, own key, loopback only)
```bash
python - <<'PY' &
from pathlib import Path
from shadowcheck import dashboard
from shadowcheck.store import Store
dashboard.KEY_FILE = Path("/tmp/sc-test-key")          # throwaway key
dashboard.serve(Store("/tmp/sc-test.db"), "/tmp/sc-test.db", 8766)
PY
adb reverse tcp:8766 tcp:8766                           # emulator's localhost:8766 -> host
```

## 2. Install and configure
```bash
cd android && ./gradlew assembleDebug && adb install -r app/build/outputs/apk/debug/app-debug.apk
for p in ACCESS_FINE_LOCATION BLUETOOTH_SCAN POST_NOTIFICATIONS NEARBY_WIFI_DEVICES; do
  adb shell pm grant app.shadowcheck android.permission.$p; done
```
Open the app, enter `http://localhost:8766`, the key from `/tmp/sc-test-key`, a place name, and
press **Start scanning**. The `AndroidWifi` AP appears within a minute.

## 3. Add virtual trackers (Bluetooth)
The emulator's netsim controller accepts extra virtual controllers over HCI on port 6402:
```bash
python tools/virtual_beacon.py --kind airtag --addr 5A:11:22:33:44:55 &
python tools/virtual_beacon.py --kind tile   --addr 6B:99:88:77:66:55 &
```
The phone's BLE scanner sees them; the server labels them "Apple Find My accessory" / "Tile tracker".

## 4. Simulate being followed
Let the app dwell ~3 minutes at one place, then type a different place name in the app and wait
another ~3 minutes. The beacons and the AP "travel" with the phone, so the server should flag both
trackers HIGH and the AP MEDIUM, and the phone should show alert notifications.

## What was verified this way (Android 17 / API 37, x86_64 emulator)
| Check | Result |
|---|---|
| Wi-Fi AP scan, upload, classification as `ap` | pass |
| BLE scan of virtual AirTag/Tile, classification as `tracker` | pass |
| Place switch while running (typing, without leaving the screen) | pass |
| Following scenario: 2 trackers HIGH + AP MEDIUM; 3 notifications on the phone | pass |
| Screen off 65 s: trackers + AP keep arriving (filtered scan) | pass |
| Stop button; Bluetooth-off start (no crash); restart after process kill | pass |
| Key field masked | pass |

## What the emulator cannot tell you
Real radio range/RSSI (the emulator reports a fixed value), vendor battery-saver behaviour,
older Android versions, and how real AirTags/Tiles behave. Test on a physical phone too.
