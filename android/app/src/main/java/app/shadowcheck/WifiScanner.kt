package app.shadowcheck

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock

/**
 * Reads nearby Wi-Fi access points. A phone cannot capture other phones' probe requests, but it
 * can see access points, and an AP that turns up at several of your places is a mobile hotspot or
 * travel router moving with someone. Android throttles active scans (about 4 per 2 minutes in the
 * foreground), so this also reads the results of scans the system runs on its own.
 */
class WifiScanner(
    context: Context,
    private val prefs: Prefs,
    private val sink: (Sighting) -> Unit,
) {
    private val ctx = context.applicationContext
    private val wm = ctx.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val handler = Handler(Looper.getMainLooper())
    private val lastSeen = HashMap<String, Long>()
    private var registered = false

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) = read()
    }

    private val poke = object : Runnable {
        @Suppress("DEPRECATION")
        override fun run() {
            try {
                if (wm.isWifiEnabled) wm.startScan() // may return false when throttled: fine
            } catch (_: SecurityException) {
            }
            read()
            handler.postDelayed(this, SCAN_EVERY_MS)
        }
    }

    fun start() {
        val f = IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
        if (Build.VERSION.SDK_INT >= 33) ctx.registerReceiver(receiver, f, Context.RECEIVER_NOT_EXPORTED)
        else ctx.registerReceiver(receiver, f)
        registered = true
        handler.post(poke)
    }

    fun stop() {
        handler.removeCallbacks(poke)
        if (registered) {
            try { ctx.unregisterReceiver(receiver) } catch (_: IllegalArgumentException) {}
            registered = false
        }
    }

    @Suppress("DEPRECATION")
    private fun read() {
        if (!wm.isWifiEnabled) {
            ScanState.wifiNote = "Wi-Fi is off"
            return
        }
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        if (Build.VERSION.SDK_INT >= 28 && !lm.isLocationEnabled) {
            ScanState.wifiNote = "turn Location on to see Wi-Fi networks"
            return
        }
        val results = try {
            wm.scanResults
        } catch (_: SecurityException) {
            ScanState.wifiNote = "location permission missing"
            return
        }
        ScanState.wifiNote = ""
        val now = SystemClock.elapsedRealtime()
        val ts = System.currentTimeMillis() / 1000.0
        if (lastSeen.size > 2000) lastSeen.clear()
        for (r in results) {
            val bssid = r.BSSID ?: continue
            if (now - (lastSeen[bssid] ?: 0L) < THROTTLE_MS) continue
            lastSeen[bssid] = now
            val ssid = (r.SSID ?: "").trim('"').takeUnless { it == "<unknown ssid>" } ?: ""
            sink(WifiObs(ts, bssid, ssid, r.level, prefs.place.ifBlank { "Phone" }))
            ScanState.apSeen++
        }
    }

    companion object {
        private const val SCAN_EVERY_MS = 35_000L
        private const val THROTTLE_MS = 10_000L
    }
}
