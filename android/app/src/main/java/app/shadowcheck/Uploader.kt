package app.shadowcheck

import android.os.Handler
import android.os.HandlerThread
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Queues observations, uploads them in batches, and polls the server for alerts. */
class Uploader(private val prefs: Prefs, private val onAlert: (String, String, String) -> Unit) {
    private val queue = ArrayDeque<Sighting>()
    private val thread = HandlerThread("shadowcheck-upload").apply { start() }
    private val handler = Handler(thread.looper)
    private val alerted = HashSet<String>()
    private var lastPoll = 0L

    private val tick = object : Runnable {
        override fun run() {
            try {
                flush()
                if (System.currentTimeMillis() - lastPoll > 60_000) {
                    lastPoll = System.currentTimeMillis()
                    pollAlerts()
                }
            } finally {
                handler.postDelayed(this, 10_000)
            }
        }
    }

    fun start() = handler.postDelayed(tick, 5_000)

    fun stop() {
        handler.removeCallbacks(tick)
        handler.post { flush() }          // best-effort final upload
        thread.quitSafely()
    }

    @Synchronized fun add(o: Sighting) {
        if (queue.size >= MAX_QUEUE) queue.removeFirst()   // drop oldest if offline for long
        queue.addLast(o)
        ScanState.queued = queue.size
    }

    @Synchronized private fun take(n: Int): List<Sighting> {
        val out = ArrayList<Sighting>(n)
        while (out.size < n && queue.isNotEmpty()) out.add(queue.removeFirst())
        ScanState.queued = queue.size
        return out
    }

    @Synchronized private fun requeue(batch: List<Sighting>) {
        for (o in batch.asReversed()) queue.addFirst(o)
        while (queue.size > MAX_QUEUE) queue.removeFirst()
        ScanState.queued = queue.size
    }

    private fun flush() {
        val base = Payload.normalizeServer(prefs.server)
        if (base.isEmpty() || prefs.key.isEmpty()) {
            ScanState.lastError = "Set server address and key"
            return
        }
        while (true) {
            val batch = take(200)
            if (batch.isEmpty()) return
            try {
                for ((place, group) in batch.groupBy { it.place }) {
                    post(
                        "$base/api/ingest",
                        Payload.build(
                            prefs.device, place,
                            group.filterIsInstance<Obs>(), group.filterIsInstance<WifiObs>(),
                        ),
                    )
                }
                ScanState.sent += batch.size
                ScanState.lastError = ""
            } catch (e: Exception) {
                requeue(batch)
                ScanState.lastError = e.message ?: e.javaClass.simpleName
                return
            }
        }
    }

    private fun conn(url: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 5_000
            readTimeout = 8_000
            setRequestProperty("Authorization", "Bearer ${prefs.key}")
        }

    private fun post(url: String, body: String) {
        val c = conn(url)
        try {
            c.requestMethod = "POST"
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body.toByteArray()) }
            if (c.responseCode !in 200..299) throw IOException("Server said HTTP ${c.responseCode}")
            c.inputStream.close()
        } finally {
            c.disconnect()
        }
    }

    /** Needs the dashboard in LAN mode (it authenticates the Bearer key there). */
    private fun pollAlerts() {
        val base = Payload.normalizeServer(prefs.server)
        if (base.isEmpty()) return
        try {
            val c = conn("$base/api/state?since=86400")
            try {
                if (c.responseCode != 200) return
                val findings = JSONObject(c.inputStream.bufferedReader().readText()).getJSONArray("findings")
                for (i in 0 until findings.length()) {
                    val f = findings.getJSONObject(i)
                    val id = f.getString("fp") + f.getString("level")
                    if (!alerted.add(id)) continue
                    val reasons = f.getJSONArray("reasons")
                    val text = (0 until reasons.length()).joinToString("; ") { reasons.getString(it) }
                    ScanState.alerts++
                    onAlert(f.getString("level"), f.optString("label").ifEmpty { f.getString("kind") }, text)
                }
            } finally {
                c.disconnect()
            }
        } catch (_: Exception) {
            // alerts are best-effort; upload errors are already surfaced
        }
    }

    companion object {
        const val MAX_QUEUE = 5000
    }
}
