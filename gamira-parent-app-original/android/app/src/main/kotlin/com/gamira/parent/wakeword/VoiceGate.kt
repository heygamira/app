package com.gamira.parent.wakeword

import org.json.JSONObject

/**
 * Energy gate, matching `src/lib/wakeword/gate.js` exactly.
 *
 * Two jobs: skip inference on silence (where most false accepts come from),
 * and save battery (an always-on service that scores room tone all day is the
 * difference between a listening app and a warm one). A hangover keeps the
 * gate open briefly after the energy drops, so the tail of a word is never
 * clipped.
 */
class VoiceGate(vad: JSONObject?) {

    private val enabled = vad?.optBoolean("enabled", true) ?: true
    private val minRmsDbfs = vad?.optDouble("min_rms_dbfs", -55.0) ?: -55.0
    private val hangoverFrames = vad?.optInt("hangover_frames", 12) ?: 12

    private var hangover = 0
    var levelDbfs: Double = SILENCE_DBFS
        private set
    var isOpen: Boolean = false
        private set

    /** Rolling noise-floor estimate, which drives the adaptive threshold. */
    var noiseFloorDbfs: Double = -60.0
        private set
    private val floorAlpha = 0.02

    /** True if inference should run for this chunk. */
    fun accept(chunk: FloatArray, length: Int = chunk.size): Boolean {
        val level = rmsDbfs(chunk, length)
        levelDbfs = level

        // Only quiet frames update the noise floor, or speech would drag it up.
        if (level < minRmsDbfs) {
            noiseFloorDbfs += floorAlpha * (level - noiseFloorDbfs)
        }

        if (!enabled) {
            isOpen = true
            return true
        }

        val active = level >= minRmsDbfs
        if (active) hangover = hangoverFrames
        else if (hangover > 0) hangover -= 1

        isOpen = active || hangover > 0
        return isOpen
    }

    fun reset() {
        hangover = 0
        isOpen = false
        noiseFloorDbfs = -60.0
    }

    companion object {
        private const val SILENCE_DBFS = -120.0

        fun rmsDbfs(chunk: FloatArray, length: Int = chunk.size): Double {
            if (length <= 0) return SILENCE_DBFS
            var sum = 0.0
            for (i in 0 until length) sum += chunk[i].toDouble() * chunk[i].toDouble()
            val rms = Math.sqrt(sum / length)
            return if (rms <= 1e-10) SILENCE_DBFS else 20.0 * Math.log10(rms)
        }
    }
}
