package com.gamira.parent.wakeword

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.util.Log
import org.json.JSONObject

/**
 * The model, the front end and the trigger, wired together — matching the
 * pipeline `src/lib/wakeword/worker.js` runs per chunk:
 *
 *   1. Gate on energy — silence never reaches the model.
 *   2. Update the rolling mel buffer (only new frames are computed).
 *   3. Run ONNX inference once enough new audio has accumulated.
 *   4. Smooth, then run the trigger state machine.
 *
 * Deliberately a straight port of the worker's control flow rather than a
 * "cleaner" rewrite: this pipeline decides whether the model ever fires, and
 * the failure mode for getting it subtly wrong is silent — the app looks
 * exactly as healthy as one that works.
 */
class WakeDetector private constructor(
    val bundle: WakeBundle,
    private val frontend: WakeFrontend,
    private val features: StreamingFeatures,
    private val gate: VoiceGate,
    private val trigger: WakeTrigger,
    private val session: OrtSession,
    private val inputName: String,
) : AutoCloseable {

    val wakeWord: String get() = bundle.wakeWord
    val sampleRate: Int get() = frontend.sampleRate

    /** One inference per this many samples: 80 ms, matching the web worker's cadence. */
    private val inferEvery = 1280
    private var sinceInfer = 0

    val levelDbfs: Double get() = gate.levelDbfs
    val noiseFloorDbfs: Double get() = gate.noiseFloorDbfs
    val isSpeaking: Boolean get() = gate.isOpen
    val rawScore: Double get() = trigger.raw
    val smoothedScore: Double get() = trigger.ema
    fun effectiveThreshold(): Double = trigger.effectiveThreshold(gate.noiseFloorDbfs)

    fun setThresholdOffset(value: Double) { trigger.thresholdOffset = value }
    fun setPreconnectThreshold(value: Double) { trigger.preconnectThreshold = value }

    /**
     * Feed one chunk of mono float32 audio at [frontend.sampleRate]. Chunks must
     * arrive in order and without gaps.
     *
     * Returns the event this chunk caused (maybe / detect / release), or null.
     */
    fun push(chunk: FloatArray, length: Int, nowMs: Long): WakeEvent? {
        if (!gate.accept(chunk, length)) {
            // Silence never reaches the model, and — matching the web worker
            // exactly — never reaches the rolling window either: the window
            // simply does not advance while the gate is shut.
            return trigger.decay(gate.noiseFloorDbfs, nowMs)
        }

        features.pushAudio(chunk, length)
        if (!features.isBufferFull) {
            sinceInfer = 0
            return null
        }
        sinceInfer += length
        if (sinceInfer < inferEvery) return null
        // Carry the remainder rather than zeroing it, capped below one full
        // interval so a stall cannot bank enough credit to burst-catch-up on
        // stale audio.
        sinceInfer = minOf(sinceInfer - inferEvery, inferEvery - 1)

        val score = infer(features.getFeatures())
        return trigger.push(score, gate.noiseFloorDbfs, nowMs)
    }

    private fun infer(flat: FloatArray): Double {
        val shape = longArrayOf(1, frontend.nFrames.toLong(), frontend.nMels.toLong(), 1)
        val environment = OrtEnvironment.getEnvironment()
        OnnxTensor.createTensor(environment, java.nio.FloatBuffer.wrap(flat), shape).use { tensor ->
            session.run(mapOf(inputName to tensor)).use { result ->
                @Suppress("UNCHECKED_CAST")
                val raw = when (val value = result[0].value) {
                    is Array<*> -> ((value as Array<FloatArray>)[0])[0]
                    is FloatArray -> value[0]
                    else -> 0f
                }
                return raw.toDouble()
            }
        }
    }

    fun reset() {
        features.reset()
        gate.reset()
        trigger.reset()
    }

    override fun close() {
        runCatching { session.close() }
    }

    companion object {
        private const val TAG = "WakeDetector"

        fun load(context: Context, options: JSONObject = JSONObject()): WakeDetector {
            val bundle = WakeBundle.load(context)
            val frontend = WakeFrontend(bundle.spec, bundle.filterbank, bundle.window)
            val features = StreamingFeatures(frontend)
            val gate = VoiceGate(bundle.manifest.optJSONObject("vad"))
            val trigger = WakeTrigger(
                bundle.manifest.getJSONObject("detector"),
                bundle.manifest.optJSONObject("adaptive_threshold"),
                options,
            )

            val environment = OrtEnvironment.getEnvironment()
            val sessionOptions = OrtSession.SessionOptions().apply {
                // Single-threaded, matching `ort.env.wasm.numThreads = 1` on the
                // web side: these matrices are small enough that thread
                // coordination costs more than it saves, and spin-waiting would
                // keep a core busy through most of every 80 ms chunk — the whole
                // battery and heat story for an always-on background service.
                setIntraOpNumThreads(1)
                setInterOpNumThreads(1)
                setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
                addConfigEntry("session.intra_op.allow_spinning", "0")
                addConfigEntry("session.inter_op.allow_spinning", "0")
            }
            val session = environment.createSession(bundle.modelBytes, sessionOptions)
            val inputName = session.inputNames.first()

            Log.i(TAG, "Loaded wake model for \"${bundle.wakeWord}\": input $inputName")

            return WakeDetector(bundle, frontend, features, gate, trigger, session, inputName)
        }
    }
}
