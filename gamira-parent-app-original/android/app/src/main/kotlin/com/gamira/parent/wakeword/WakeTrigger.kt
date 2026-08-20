package com.gamira.parent.wakeword

import org.json.JSONObject

enum class WakeEventType { MAYBE, DETECT, RELEASE }

data class WakeEvent(
    val type: WakeEventType,
    val smoothed: Double = 0.0,
    val threshold: Double = 0.0,
    val confidence: Double = 0.0,
    val peak: Double = 0.0,
)

/**
 * The trigger state machine, matching `src/lib/wakeword/trigger.js` exactly.
 *
 * Rising-edge with hysteresis and a refractory window, plus a second, lower
 * threshold ("maybe") that fires long before the detector is willing to
 * commit — this app uses it to start opening a Gemini Live session
 * speculatively, so the socket is already up by the time the wake word is
 * confirmed. It shares the same hysteresis as the real trigger, so the two
 * can never disagree about whether an utterance is still in progress.
 *
 * @param detector the manifest's `detector` block
 * @param adaptive the manifest's `adaptive_threshold` block
 */
class WakeTrigger(detector: JSONObject, adaptive: JSONObject?, options: JSONObject = JSONObject()) {

    var threshold: Double = detector.getDouble("threshold")
        private set
    private val rawThreshold = detector.getDouble("raw_threshold")
    private val releaseThreshold = detector.getDouble("release_threshold")
    private val consecutiveRequired = detector.getInt("consecutive_hits")
    private val refractoryPeriod = detector.getDouble("refractory_period")
    private val alpha = 2.0 / (detector.getDouble("smoothing_window") + 1)

    private val adaptiveEnabled = adaptive?.optBoolean("enabled", true) ?: true
    private val adaptiveMaxBoost = adaptive?.optDouble("max_boost", 0.15) ?: 0.15

    @Volatile var preconnectThreshold: Double = options.optDouble("preconnectThreshold", 0.4)
    @Volatile var thresholdOffset: Double = options.optDouble("thresholdOffset", 0.0)

    var raw: Double = 0.0
        private set
    var ema: Double = 0.0
        private set
    private var armed = true
    private var hits = 0
    private var peak = 0.0
    private var lastDetectionAtMs = 0L
    private var maybeOpen = false

    /** The threshold in force right now. A noisy room raises the bar. */
    fun effectiveThreshold(noiseFloorDbfs: Double): Double {
        val base = minOf(0.99, maxOf(0.05, threshold + thresholdOffset))
        if (!adaptiveEnabled) return base
        val excess = maxOf(0.0, noiseFloorDbfs + 60.0) / 30.0
        return minOf(0.99, base + minOf(adaptiveMaxBoost, adaptiveMaxBoost * excess))
    }

    /** A new model score. Returns the event this caused, or null. */
    fun push(score: Double, noiseFloorDbfs: Double, nowMs: Long): WakeEvent? {
        raw = score
        ema = alpha * score + (1 - alpha) * ema
        return evaluate(noiseFloorDbfs, nowMs)
    }

    /** The gate closed, so no score was produced: let the smoothed score fall away. */
    fun decay(noiseFloorDbfs: Double, nowMs: Long): WakeEvent? {
        raw = 0.0
        ema *= 1 - alpha
        if (ema < releaseThreshold) {
            armed = true
            hits = 0
        }
        return evaluate(noiseFloorDbfs, nowMs)
    }

    private fun evaluate(noiseFloorDbfs: Double, nowMs: Long): WakeEvent? {
        val effective = effectiveThreshold(noiseFloorDbfs)
        var event: WakeEvent? = null

        val above = ema >= effective && raw >= rawThreshold
        hits = if (above) hits + 1 else 0
        peak = maxOf(peak, ema)

        if (!maybeOpen && armed && ema >= preconnectThreshold) {
            maybeOpen = true
            event = WakeEvent(WakeEventType.MAYBE, smoothed = ema, threshold = effective)
        }

        if (armed && hits >= consecutiveRequired) {
            if (nowMs - lastDetectionAtMs > refractoryPeriod * 1000) {
                lastDetectionAtMs = nowMs
                event = WakeEvent(
                    WakeEventType.DETECT,
                    confidence = raw,
                    smoothed = ema,
                    peak = maxOf(peak, ema),
                    threshold = effective,
                )
            }
            armed = false
            hits = 0
        }

        if (ema < releaseThreshold) {
            if (!armed) {
                armed = true
                peak = 0.0
            }
            if (maybeOpen) {
                maybeOpen = false
                if (event == null) event = WakeEvent(WakeEventType.RELEASE)
            }
        }

        return event
    }

    fun reset() {
        raw = 0.0
        ema = 0.0
        armed = true
        hits = 0
        peak = 0.0
        maybeOpen = false
    }
}
