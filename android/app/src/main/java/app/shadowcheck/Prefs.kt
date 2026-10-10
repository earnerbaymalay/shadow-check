package app.shadowcheck

import android.content.Context
import android.content.SharedPreferences
import android.os.Build

class Prefs(ctx: Context) {
    // App-private storage; backups are disabled in the manifest so the key never leaves the phone.
    val sp: SharedPreferences = ctx.getSharedPreferences("shadowcheck", Context.MODE_PRIVATE)

    var server: String
        get() = sp.getString("server", "") ?: ""
        set(v) = sp.edit().putString("server", v).apply()
    var key: String
        get() = sp.getString("key", "") ?: ""
        set(v) = sp.edit().putString("key", v).apply()
    var place: String
        get() = sp.getString("place", "") ?: ""
        set(v) = sp.edit().putString("place", v).apply()
    var device: String
        get() = sp.getString("device", Build.MODEL ?: "android") ?: "android"
        set(v) = sp.edit().putString("device", v).apply()
    var enabled: Boolean
        get() = sp.getBoolean("enabled", false)
        set(v) = sp.edit().putBoolean("enabled", v).apply()
}

/** Live status shared between the service and the screen. */
object ScanState {
    @Volatile var running = false
    @Volatile var seen = 0L
    @Volatile var sent = 0L
    @Volatile var queued = 0
    @Volatile var filtered = false      // true while the screen is off (tracker-only scan)
    @Volatile var lastError = ""
    @Volatile var alerts = 0
    @Volatile var apSeen = 0L
    @Volatile var wifiNote = ""
}
