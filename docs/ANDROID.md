# Shadow Check for Android

The Android app is a **sensor**: it scans Bluetooth LE on the phone and sends raw
advertisements to your Shadow Check dashboard. The dashboard does all analysis and the
phone shows alerts as notifications. A phone is the right sensor for a protected person
because it is always with them.

## Requirements
- Android 8.0+ (API 26) with Bluetooth LE.
- Android Studio (project uses Gradle 8.11 / AGP 8.9, Kotlin 2.1, JDK 17+).
- A reachable dashboard: `shadowcheck dashboard --host <ip>` on your computer.

## Build and install
1. *File ▸ Open…* and choose the `android/` folder; wait for Gradle sync.
2. Enable USB debugging on the phone, connect it, press ▶ Run, or
   *Build ▸ Build APK(s)* and sideload `app/build/outputs/apk/debug/app-debug.apk`.
3. Command line (optional): `cd android && ./gradlew assembleDebug` (generate the wrapper
   once in Studio, or run `gradle wrapper`).

## Pair with the dashboard
1. On the computer: `shadowcheck dashboard --host 100.x.y.z` (your Tailscale IP) or your LAN IP.
2. Open the dashboard and click **Connect phone**: it lists server addresses and the key.
3. In the app enter the address (e.g. `http://100.x.y.z:8765`), the key, the place name and a
   phone name, then **Start scanning**. Change the place when you move.

## Permissions (and why)
| Permission | Reason |
|---|---|
| Bluetooth scan (Android 12+) / Bluetooth + Location (≤11) | find nearby advertisements |
| Fine location | required by Android for BLE scan results; not uploaded |
| Foreground service (connected device, location) | keep scanning with the screen locked |
| Notifications | scan status and alerts |
| Internet | upload to *your* dashboard only |

The app does **not** use Android's `neverForLocation` flag, because that flag hides some
tracker beacons, which is the thing we most want to see.

## Behaviour and limitations
- **Screen on:** scans every device. **Screen off:** Android pauses unfiltered scans, so the app
  switches to tracker-only filters (Apple Find My, Tile, SmartTag, Chipolo) and resumes the full
  scan when the screen turns on.
- Sightings are throttled to one per device per 5 s and queued (up to 5000) while offline.
- Android does not tell the app whether an address is public or random, so classification uses
  the address bits. Some public addresses may be treated as rotating (weaker fingerprints).
- Aggressive battery optimisation (some Xiaomi/Huawei/Samsung modes) can kill the service;
  exempt the app from battery optimisation.
- Alerts require the dashboard in LAN mode (`--host`), since the app polls `/api/state`.
- Traffic is plain HTTP. Use Tailscale/another VPN. The key is stored in app-private storage and
  Android backups are disabled.

## Troubleshooting the build
- **"25.0.3" / unsupported Java version:** Gradle 8.11 cannot run on Java 25. In Android Studio set
  *Settings ▸ Build Tools ▸ Gradle ▸ Gradle JDK* to a JDK 17 or 21. On the command line set
  `JAVA_HOME` to JDK 17/21 and `ANDROID_HOME` to your SDK, then `./gradlew assembleDebug`.
- Needs SDK Platform 35 and Build-Tools 35.0.0 (Studio installs them on sync).
- The Android emulator cannot do Bluetooth LE scanning: test on a real phone.

## Status
Verified: `assembleDebug` succeeds and the JVM unit tests (upload payload contract) pass.
Not yet verified on physical hardware: BLE scanning, the screen-off tracker filters, the
foreground-service behaviour on different Android versions, and notification delivery.
Reports welcome.
