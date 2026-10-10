package app.shadowcheck

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.ParcelUuid
import android.os.SystemClock

/**
 * Foreground BLE scanner. Android pauses unfiltered scans while the screen is off, so
 * with the screen off it switches to tracker-only filters (AirTag/Tile/SmartTag/Chipolo)
 * and goes back to scanning everything when the screen turns on.
 */
class ScanService : Service() {
    private lateinit var prefs: Prefs
    private lateinit var uploader: Uploader
    private var scanner: BluetoothLeScanner? = null
    private var wifi: WifiScanner? = null
    private val lastSeen = HashMap<String, Long>()

    private val callback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) = handle(result)
        override fun onBatchScanResults(results: MutableList<ScanResult>) = results.forEach(::handle)
        override fun onScanFailed(errorCode: Int) {
            ScanState.lastError = "Bluetooth scan failed (code $errorCode)"
        }
    }

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            startScan(filtered = i.action == Intent.ACTION_SCREEN_OFF)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        prefs = Prefs(this)
        if (intent?.action == ACTION_STOP) {
            prefs.enabled = false
            stopSelf()
            return START_NOT_STICKY
        }
        if (ScanState.running) return START_STICKY
        // startForegroundService() requires startForeground() within seconds on every path.
        createChannels()
        val n = notification("Scanning for recurring devices")
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(
                1, n,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION,
            )
        } else {
            startForeground(1, n)
        }
        // intent == null means Android restarted us after killing the process.
        if (intent == null && !prefs.enabled) {
            stopSelf()
            return START_NOT_STICKY
        }
        val adapter = (getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
        if (adapter == null || !adapter.isEnabled) {
            ScanState.lastError = "Bluetooth is off"
            prefs.enabled = false
            stopSelf()
            return START_NOT_STICKY
        }
        prefs.enabled = true
        scanner = adapter.bluetoothLeScanner
        uploader = Uploader(prefs) { level, title, text -> alert(level, title, text) }
        uploader.start()
        val f = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
        }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(screenReceiver, f, Context.RECEIVER_NOT_EXPORTED)
        else registerReceiver(screenReceiver, f)
        wifi = WifiScanner(this, prefs) { uploader.add(it) }.also { it.start() }
        ScanState.running = true
        startScan(filtered = false)
        return START_STICKY
    }

    override fun onDestroy() {
        if (ScanState.running) {
            try { unregisterReceiver(screenReceiver) } catch (_: IllegalArgumentException) {}
            try { scanner?.stopScan(callback) } catch (_: SecurityException) {} catch (_: IllegalStateException) {}
            wifi?.stop()
            uploader.stop()
        }
        ScanState.running = false
        super.onDestroy()
    }

    private fun startScan(filtered: Boolean) {
        val s = scanner ?: return
        try {
            s.stopScan(callback)
            val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_BALANCED).build()
            s.startScan(if (filtered) trackerFilters() else null, settings, callback)
            ScanState.filtered = filtered
        } catch (e: SecurityException) {
            ScanState.lastError = "Bluetooth/location permission missing"
        } catch (e: IllegalStateException) {
            ScanState.lastError = "Bluetooth unavailable"
        }
    }

    private fun handle(r: ScanResult) {
        val addr = r.device.address ?: return
        val now = SystemClock.elapsedRealtime()
        if (now - (lastSeen[addr] ?: 0L) < THROTTLE_MS) return
        if (lastSeen.size > 4000) lastSeen.clear()
        lastSeen[addr] = now

        val rec = r.scanRecord
        val mfr = HashMap<Int, ByteArray>()
        rec?.manufacturerSpecificData?.let { for (i in 0 until it.size()) mfr[it.keyAt(i)] = it.valueAt(i) }
        val svc = HashMap<String, ByteArray>()
        rec?.serviceData?.forEach { (k, v) -> svc[k.toString()] = v }
        val tx = rec?.txPowerLevel?.takeIf { it != Int.MIN_VALUE }
        uploader.add(
            Obs(
                ts = System.currentTimeMillis() / 1000.0,
                addr = addr,
                rssi = r.rssi,
                name = rec?.deviceName,
                mfr = mfr,
                uuids = rec?.serviceUuids?.map { it.toString() } ?: emptyList(),
                svc = svc,
                tx = tx,
                place = prefs.place.ifBlank { "Phone" },
            )
        )
        ScanState.seen++
    }

    private fun trackerFilters(): List<ScanFilter> {
        val out = ArrayList<ScanFilter>()
        // Apple "Find My" offline-finding advert: manufacturer 0x004C, first payload byte 0x12.
        out += ScanFilter.Builder()
            .setManufacturerData(0x004C, byteArrayOf(0x12), byteArrayOf(0xFF.toByte()))
            .build()
        for (short in TRACKER_UUIDS) {
            val u = ParcelUuid.fromString("0000$short-0000-1000-8000-00805f9b34fb")
            out += ScanFilter.Builder().setServiceUuid(u).build()
            out += ScanFilter.Builder().setServiceData(u, byteArrayOf(), byteArrayOf()).build()
        }
        return out
    }

    private fun createChannels() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CH_SCAN, "Scanning", NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(
            NotificationChannel(CH_ALERT, "Alerts", NotificationManager.IMPORTANCE_HIGH))
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, ScanService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CH_SCAN)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("Shadow Check")
            .setContentText(text)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Stop", stop).build())
            .setOngoing(true)
            .build()
    }

    private fun alert(level: String, title: String, text: String) {
        val open = PendingIntent.getActivity(
            this, 2, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CH_ALERT)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("Shadow Check $level: $title")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try {
            getSystemService(NotificationManager::class.java).notify((title + text).hashCode(), n)
        } catch (_: SecurityException) {
            // notification permission denied: alert still counted in the app
        }
    }

    companion object {
        const val ACTION_STOP = "app.shadowcheck.STOP"
        private const val CH_SCAN = "scan"
        private const val CH_ALERT = "alert"
        private const val THROTTLE_MS = 5_000L
        private val TRACKER_UUIDS = listOf("feed", "fd84", "fd5a", "fe33")
    }
}
