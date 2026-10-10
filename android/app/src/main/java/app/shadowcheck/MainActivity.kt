package app.shadowcheck

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var server: EditText
    private lateinit var key: EditText
    private lateinit var place: EditText
    private lateinit var device: EditText
    private lateinit var toggle: Button
    private lateinit var status: TextView
    private val ui = Handler(Looper.getMainLooper())
    private var note = ""

    private val refresh = object : Runnable {
        override fun run() {
            render()
            ui.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }
        fun label(t: String) = TextView(this).apply { text = t; setPadding(0, pad / 2, 0, 0) }
        fun field(hint: String, value: String, type: Int = InputType.TYPE_CLASS_TEXT) =
            EditText(this).apply { this.hint = hint; setText(value); inputType = type; setSingleLine() }

        col.addView(TextView(this).apply { text = "Shadow Check"; textSize = 24f })
        col.addView(TextView(this).apply {
            text = "Scans nearby Bluetooth devices and sends them to your Shadow Check dashboard, " +
                "which flags devices or trackers that keep turning up wherever you go."
        })
        col.addView(label("Dashboard address (from “Connect phone”)"))
        server = field("http://100.x.x.x:8765", prefs.server, InputType.TYPE_TEXT_VARIATION_URI)
        col.addView(server)
        col.addView(label("Key"))
        key = field("paste key", prefs.key, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        col.addView(key)
        col.addView(label("Where are you? (change when you move)"))
        place = field("Home, Gym, Office…", prefs.place)
        col.addView(place)
        col.addView(label("This phone's name"))
        device = field("Pixel", prefs.device)
        col.addView(device)

        toggle = Button(this).apply { setOnClickListener { onToggle() } }
        col.addView(toggle)
        status = TextView(this).apply { setPadding(0, pad, 0, 0) }
        col.addView(status)
        col.addView(TextView(this).apply {
            setPadding(0, pad, 0, 0)
            text = "Screen on: scans every device. Screen off: Android only allows tracker-specific " +
                "scanning (AirTag, Tile, SmartTag, Chipolo)."
        })
        setContentView(ScrollView(this).apply { addView(col) })
    }

    override fun onResume() { super.onResume(); ui.post(refresh) }
    override fun onPause() { super.onPause(); ui.removeCallbacks(refresh); save() }

    private fun save() {
        prefs.server = server.text.toString()
        prefs.key = key.text.toString().trim()
        prefs.place = place.text.toString().trim()
        prefs.device = device.text.toString().trim().ifEmpty { "android" }
    }

    private fun needed(): List<String> {
        val p = ArrayList<String>()
        if (Build.VERSION.SDK_INT >= 31) p += Manifest.permission.BLUETOOTH_SCAN
        p += Manifest.permission.ACCESS_FINE_LOCATION
        if (Build.VERSION.SDK_INT >= 33) p += Manifest.permission.POST_NOTIFICATIONS
        return p
    }

    private fun missingRequired() = needed().filter {
        it != Manifest.permission.POST_NOTIFICATIONS &&
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
    }

    private fun onToggle() {
        save()
        if (ScanState.running) {
            startService(Intent(this, ScanService::class.java).setAction(ScanService.ACTION_STOP))
            return
        }
        if (prefs.server.isBlank() || prefs.key.isBlank() || prefs.place.isBlank()) {
            note = "Fill in the dashboard address, key and place first."
            render()
            return
        }
        if (missingRequired().isNotEmpty()) {
            requestPermissions(needed().toTypedArray(), 1)
        } else {
            startForegroundService(Intent(this, ScanService::class.java))
        }
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, res: IntArray) {
        if (missingRequired().isEmpty()) startForegroundService(Intent(this, ScanService::class.java))
        else {
            note = "Bluetooth scan and location permissions are required to find nearby devices."
            render()
        }
    }

    private fun render() {
        toggle.text = if (ScanState.running) "Stop scanning" else "Start scanning"
        status.text = buildString {
            append(if (ScanState.running) {
                if (ScanState.filtered) "Scanning (screen off: trackers only)" else "Scanning all devices"
            } else "Stopped")
            append("\nSeen: ${ScanState.seen}   Sent: ${ScanState.sent}   Queued: ${ScanState.queued}")
            append("\nAlerts raised: ${ScanState.alerts}")
            if (ScanState.lastError.isNotEmpty()) append("\n⚠ ${ScanState.lastError}")
            if (note.isNotEmpty() && !ScanState.running) append("\n$note")
        }
    }
}
