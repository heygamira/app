package com.gamira.parent.wakeword

/**
 * Rolling audio and mel buffers, matching `src/lib/wakeword/stream.js` exactly.
 *
 * Recomputing all 151 mel frames on every 80 ms chunk would be ~19x redundant
 * STFT work for the 8 frames that are actually new. Because front end v2 is
 * uncentred, every frame is a pure function of an absolute audio position, so
 * only the new frames need computing and the result is bit-identical to
 * analysing the whole window offline.
 */
class StreamingFeatures(private val frontend: WakeFrontend) {

    private val nSamples = frontend.nSamples
    private val nMels = frontend.nMels
    private val nFrames = frontend.nFrames
    private val hopLength = frontend.hopLength
    private val nFft = frontend.nFft

    private val audio = DoubleArray(nSamples)
    private val mel = FloatArray(nMels * nFrames)
    // Samples not yet consumed. The analysis window only ever advances in
    // whole hops, or the audio ring and the mel ring drift apart.
    private var stage = DoubleArray(hopLength)
    private var staged = 0
    private var received = 0L

    private val features = FloatArray(nFrames * nMels)

    val isBufferFull: Boolean get() = received >= nSamples

    /** Feed mono audio at the front end's sample rate. Any chunk length is accepted. */
    fun pushAudio(chunk: FloatArray, length: Int = chunk.size) {
        if (length <= 0) return
        received += length

        var offset = 0
        if (staged > 0) {
            val need = hopLength - staged
            val take = minOf(need, length)
            for (i in 0 until take) stage[staged + i] = chunk[i].toDouble()
            staged += take
            offset = take
            if (staged < hopLength) return
            shiftAudio(stage, hopLength)
            advanceMel(1)
            staged = 0
        }

        val remaining = length - offset
        val whole = (remaining / hopLength) * hopLength
        if (whole > 0) {
            // A temporary double view of chunk[offset, offset+whole) — sized
            // once per call, not per sample.
            val block = DoubleArray(whole) { chunk[offset + it].toDouble() }
            shiftAudio(block, whole)
            advanceMel(whole / hopLength)
            offset += whole
        }

        val leftover = length - offset
        if (leftover > 0) {
            for (i in 0 until leftover) stage[i] = chunk[offset + i].toDouble()
            staged = leftover
        }
    }

    private fun shiftAudio(samples: DoubleArray, count: Int) {
        if (count >= nSamples) {
            System.arraycopy(samples, count - nSamples, audio, 0, nSamples)
            return
        }
        System.arraycopy(audio, count, audio, 0, nSamples - count)
        System.arraycopy(samples, 0, audio, nSamples - count, count)
    }

    /** Compute exactly the [k] mel frames the newly arrived audio unlocked. */
    private fun advanceMel(k: Int) {
        if (k <= 0) return

        if (k >= nFrames) {
            for (t in 0 until nFrames) frontend.melFrameInto(audio, t * hopLength, mel, t, nFrames)
            return
        }

        for (m in 0 until nMels) {
            val row = m * nFrames
            System.arraycopy(mel, row + k, mel, row, nFrames - k)
        }
        val start = nSamples - nFft - (k - 1) * hopLength
        for (i in 0 until k) {
            frontend.melFrameInto(audio, start + i * hopLength, mel, nFrames - k + i, nFrames)
        }
    }

    /** Model input: `nFrames x nMels` float32, flattened row-major. Reused between calls. */
    fun getFeatures(): FloatArray {
        frontend.pcenInto(mel, features)
        return features
    }

    fun reset() {
        java.util.Arrays.fill(audio, 0.0)
        java.util.Arrays.fill(mel, 0f)
        staged = 0
        received = 0
    }
}
