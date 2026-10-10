package app.shadowcheck

import org.json.JSONArray
import org.json.JSONObject

/** Anything the phone sensed; carries the place label it was sensed at. */
sealed interface Sighting {
    val place: String
}

/** One Wi-Fi access point from a scan (phones see APs, not other phones). */
data class WifiObs(
    val ts: Double,
    val bssid: String,
    val ssid: String,
    val rssi: Int,
    override val place: String,
) : Sighting

/** One BLE advertisement, kept raw: the server computes the fingerprint. */
data class Obs(
    val ts: Double,
    val addr: String,
    val rssi: Int,
    val name: String?,
    val mfr: Map<Int, ByteArray>,
    val uuids: List<String>,
    val svc: Map<String, ByteArray>,
    val tx: Int?,
    override val place: String,
) : Sighting

/** Server accepts at most 62 bytes per payload. */
fun ByteArray.toHex(): String =
    take(62).joinToString("") { "%02x".format(it.toInt() and 0xFF) }

object Payload {
    fun build(device: String, place: String, obs: List<Obs>, wifi: List<WifiObs> = emptyList()): String {
        val arr = JSONArray()
        for (x in obs) {
            val j = JSONObject()
            j.put("ts", x.ts)
            j.put("addr", x.addr)
            j.put("rssi", x.rssi)
            x.name?.let { j.put("name", it) }
            if (x.mfr.isNotEmpty()) {
                val m = JSONObject()
                x.mfr.forEach { (k, v) -> m.put(k.toString(), v.toHex()) }
                j.put("mfr", m)
            }
            if (x.uuids.isNotEmpty()) j.put("uuids", JSONArray(x.uuids))
            if (x.svc.isNotEmpty()) {
                val s = JSONObject()
                x.svc.forEach { (k, v) -> s.put(k, v.toHex()) }
                j.put("svc", s)
            }
            x.tx?.let { j.put("tx", it) }
            arr.put(j)
        }
        val aps = JSONArray()
        for (w in wifi) {
            aps.put(JSONObject().put("ts", w.ts).put("bssid", w.bssid).put("ssid", w.ssid).put("rssi", w.rssi))
        }
        return JSONObject().put("device", device).put("place", place)
            .put("observations", arr).put("wifi", aps).toString()
    }

    fun normalizeServer(raw: String): String {
        var s = raw.trim().trimEnd('/')
        if (s.isNotEmpty() && !s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
        return s
    }
}
