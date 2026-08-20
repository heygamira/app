package com.gamira.parent.wakeword

import org.json.JSONObject

/**
 * How audio becomes model input — parsed from `public/wake/<version>/frontend.json`,
 * the same file `src/lib/wakeword/frontend.js` reads on the web side.
 *
 * Front end v2 only: magnitude mel (power = 1), `center = false`, PCEN. Refuse
 * anything else rather than guess, for the same reason the JS side does: a
 * model fed the wrong features loads cleanly, runs at full speed, and simply
 * never fires.
 */
data class WakeFrontendSpec(
    val version: Int,
    val sampleRate: Int,
    val nMels: Int,
    val nFft: Int,
    val hopLength: Int,
    val winLength: Int,
    val center: Boolean,
    val power: Double,
    val normalization: String,
    val nFrames: Int,
    val pcen: Pcen,
) {
    data class Pcen(
        val alpha: Double,
        val delta: Double,
        val r: Double,
        val eps: Double,
        /** Resolved by the exporter, not recomputed here — see WakeFrontend.pcenInto. */
        val smootherB: Double,
        val smootherZi: Double,
        /** "constant" or "scaled" — which lfilter seed librosa used for this export. */
        val smootherInit: String,
    )

    /** Frame `t` covers `[t*hop, t*hop + nFft)`, so a window of `nFrames` needs this many samples. */
    val nSamples: Int
        get() = if (center) (nFrames - 1) * hopLength else nFft + (nFrames - 1) * hopLength

    val nBins: Int
        get() = nFft / 2 + 1

    /** Why this spec cannot be used, or null if it can. Mirrors `describeSpecMismatch` in frontend.js. */
    fun describeMismatch(): String? {
        if (version != SUPPORTED_VERSION) {
            return "this build implements front end v$SUPPORTED_VERSION, the model wants v$version"
        }
        if (center) return "center=true is not supported (v2 models are uncentred)"
        if (power != 1.0) return "power=$power is not supported (v2 uses magnitude)"
        if (normalization != "pcen") return "normalization=$normalization is not supported"
        if (pcen.smootherInit != "constant" && pcen.smootherInit != "scaled") {
            return "unknown PCEN initialisation \"${pcen.smootherInit}\""
        }
        return null
    }

    companion object {
        const val SUPPORTED_VERSION = 2

        fun fromJson(json: JSONObject): WakeFrontendSpec {
            val pcenJson = json.optJSONObject("pcen")
                ?: throw IllegalArgumentException("the bundle predates the resolved PCEN smoother")
            val smoother = pcenJson.optJSONObject("smoother")
                ?: throw IllegalArgumentException(
                    "the bundle predates the resolved PCEN smoother; re-run the exporter",
                )
            return WakeFrontendSpec(
                version = json.optInt("version", 2),
                sampleRate = json.optInt("sample_rate", 16000),
                nMels = json.optInt("n_mels", 80),
                nFft = json.optInt("n_fft", 512),
                hopLength = json.optInt("hop_length", 160),
                winLength = json.optInt("win_length", 400),
                center = json.optBoolean("center", false),
                power = json.optDouble("power", 1.0),
                normalization = json.optString("normalization", "pcen"),
                nFrames = json.optInt("n_frames", 151),
                pcen = Pcen(
                    alpha = pcenJson.optDouble("alpha"),
                    delta = pcenJson.optDouble("delta"),
                    r = pcenJson.optDouble("r"),
                    eps = pcenJson.optDouble("eps"),
                    smootherB = smoother.optDouble("b"),
                    smootherZi = smoother.optDouble("zi"),
                    smootherInit = smoother.optString("init", "constant"),
                ),
            )
        }
    }
}
