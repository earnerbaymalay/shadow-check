package app.shadowcheck

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class PayloadTest {
    private val airtag = Obs(
        ts = 1.75e9, addr = "5A:11:22:33:44:55", rssi = -60, name = null,
        mfr = mapOf(0x004C to byteArrayOf(0x12, 0x19)), uuids = emptyList(),
        svc = emptyMap(), tx = null, place = "Gym",
    )

    @Test fun hexIsLowercaseAndCapped() {
        assertEquals("12ff", byteArrayOf(0x12, 0xFF.toByte()).toHex())
        assertEquals(124, ByteArray(100).toHex().length)
    }

    @Test fun payloadMatchesServerContract() {
        val j = JSONObject(Payload.build("pixel", "Gym", listOf(airtag)))
        assertEquals("Gym", j.getString("place"))
        val o = j.getJSONArray("observations").getJSONObject(0)
        assertEquals("5A:11:22:33:44:55", o.getString("addr"))
        assertEquals("1219", o.getJSONObject("mfr").getString("76")) // company id as decimal string
        assertFalse(o.has("name"))
        assertFalse(o.has("tx"))
    }

    @Test fun serverAddressIsNormalised() {
        assertEquals("http://100.64.0.1:8765", Payload.normalizeServer(" 100.64.0.1:8765/ "))
        assertEquals("https://x.example", Payload.normalizeServer("https://x.example"))
    }

    @Test fun wifiAccessPointsAreIncluded() {
        val ap = WifiObs(1.75e9, "00:13:10:85:fe:01", "AndroidWifi", -45, "Gym")
        val j = JSONObject(Payload.build("pixel", "Gym", emptyList(), listOf(ap)))
        val w = j.getJSONArray("wifi").getJSONObject(0)
        assertEquals("00:13:10:85:fe:01", w.getString("bssid"))
        assertEquals("AndroidWifi", w.getString("ssid"))
        assertEquals(-45, w.getInt("rssi"))
        assertEquals(0, j.getJSONArray("observations").length())
    }
}
