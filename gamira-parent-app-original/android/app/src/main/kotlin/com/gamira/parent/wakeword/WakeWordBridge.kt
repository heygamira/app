package com.gamira.parent.wakeword

import android.content.Context
import android.util.Base64
import android.util.Log
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

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

    /**
     * True while a Gemini Live session, not the wake-word model, owns the
     * microphone stream.
     *
     * This phone's WebView cannot open `getUserMedia` at all — verified
     * directly: a fresh page, before this service ever touches the
     * microphone, still gets `NotReadableError: Could not start audio
     * source`, while native `AudioRecord` opens fine at the same moment. So
     * rather than let the voice session try (and fail) to open its own
     * stream, the *same* AudioRecord this service already has open just
     * switches what it does with each chunk: score it against the wake-word
     * model, or hand it to `geminiVoice.js` as the conversation's audio
     * input. One microphone, one mode flag, never two concurrent opens to
     * race or fail.
     */
    @Volatile var audioTapActive: Boolean = false
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

    /**
     * A voice session wants the microphone. Scoring stops — resetting the
     * trigger/features/gate so nothing stale is waiting when scoring resumes
     * — and the capture loop starts handing chunks to [emitAudioChunk]
     * instead. The AudioRecord itself is untouched.
     */
    fun beginAudioTap() {
        detector?.reset()
        audioTapActive = true
    }

    /** The voice session ended; go back to listening for the wake word. */
    fun endAudioTap() {
        audioTapActive = false
        detector?.reset()
    }

    fun setOptions(thresholdOffset: Double?, preconnectThreshold: Double?) {
        val d = detector ?: return
        thresholdOffset?.let { d.setThresholdOffset(it) }
        preconnectThreshold?.let { d.setPreconnectThreshold(it) }
    }

    fun onListeningChanged(value: Boolean) {
        isListening = value
        emit("listening", JSONObject().put("listening", value))
    }

    fun onMicLost(message: String) {
        isListening = false
        emit("error", JSONObject().put("message", message))
    }

    /**
     * Hand one chunk of mono float32 audio to the JS side, while
     * [audioTapActive] is true.
     *
     * Base64 of raw little-endian float32 bytes — the same layout
     * `new Float32Array(arrayBuffer)` reads on the web side, so
     * `nativeEngine.js` decodes it into exactly the `Float32Array` shape
     * `geminiVoice.js`'s `audioSource.subscribe` callback already expects
     * from the *web* wake-word engine's own worklet tap. Nothing downstream
     * of that callback needs to know which one produced the chunk.
     */
    fun emitAudioChunk(buffer: FloatArray, length: Int) {
        if (length <= 0) return
        val bytes = ByteBuffer.allocate(length * 4).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until length) bytes.putFloat(buffer[i])
        val encoded = Base64.encodeToString(bytes.array(), Base64.NO_WRAP)
        emit("audio", JSONObject().put("pcm", encoded).put("samples", length))
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
