package com.gamira.parent.wakeword

import android.content.Context
import android.util.Log
import org.json.JSONObject

/**
 * The one detector, shared by the foreground service and the Capacitor
 * plugin. A singleton because the microphone is one: both sides have to be
 * looking at the same detector, and re-creating it per call would mean
 * reloading a 3 MB ONNX graph on every start/stop.
 */
object WakeWordBridge {
    private const val TAG = "WakeWordBridge"

    @Volatile var detector: WakeDetector? = null
        private set

    @Volatile var isListening: Boolean = false
        internal set

    /** Set from JS via `pause()` while a voice session is live; Gamira's own
     * reply is in the room, and the detector should not try to wake on it. */
    @Volatile var paused: Boolean = false
        internal set

    private var listener: ((String, JSONObject) -> Unit)? = null

    fun onEvent(handler: ((String, JSONObject) -> Unit)?) {
        listener = handler
    }

    fun emit(event: String, payload: JSONObject) {
        runCatching { listener?.invoke(event, payload) }
            .onFailure { Log.w(TAG, "listener threw", it) }
    }

    /** Load the bundle once, up front, so the first `start()` is not the one that pays for it. */
    @Synchronized
    fun ensureLoaded(context: Context, options: JSONObject = JSONObject()): WakeDetector {
        detector?.let { return it }
        val loaded = WakeDetector.load(context.applicationContext, options)
        detector = loaded
        emit("ready", JSONObject().put("wakeWord", loaded.wakeWord).put("threshold", loaded.effectiveThreshold()))
        return loaded
    }

    fun setOptions(thresholdOffset: Double?, preconnectThreshold: Double?) {
        val d = detector ?: return
        thresholdOffset?.let { d.setThresholdOffset(it) }
        preconnectThreshold?.let { d.setPreconnectThreshold(it) }
    }

    /**
     * Stop scoring but keep every resource warm — the microphone, the ONNX
     * session, the notification. Used while a voice session is live: Gamira's
     * own reply is in the room and should not wake her again.
     *
     * Resets the trigger/features/gate immediately, matching the web worker's
     * `pause` handler: held open rather than torn down, but with no stale
     * state left over for when scoring resumes.
     */
    fun pause() {
        paused = true
        detector?.reset()
    }

    fun resume() {
        paused = false
    }

    fun onListeningChanged(value: Boolean) {
        isListening = value
        emit("listening", JSONObject().put("listening", value))
    }

    fun onMicLost(message: String) {
        isListening = false
        emit("error", JSONObject().put("message", message))
    }

    fun onEvent(event: WakeEvent) {
        val payload = JSONObject()
            .put("type", event.type.name.lowercase())
            .put("smoothed", event.smoothed)
            .put("threshold", event.threshold)
        when (event.type) {
            WakeEventType.MAYBE -> emit("maybe", payload)
            WakeEventType.DETECT -> emit(
                "detect",
                payload.put("confidence", event.confidence).put("peak", event.peak),
            )
            WakeEventType.RELEASE -> emit("release", payload)
        }
    }
}
