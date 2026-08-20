package com.gamira.parent.wakeword

/**
 * Audio to model input, matching `src/lib/wakeword/frontend.js` exactly.
 *
 * The mel filterbank and the analysis window are NOT computed here, same as
 * the web version and for the same reason: they are shipped as float32 blobs
 * by the trainer's exporter (`mel_filterbank.f32`, `window.f32`), taken
 * straight off the Python `Frontend` instance. Re-deriving librosa's
 * Slaney-normalised mel filterbank independently here is exactly the kind of
 * near-miss that costs days and never throws — the model still loads, still
 * runs, and simply never fires.
 *
 * @param filterbank `nMels x nBins`, row-major
 * @param window `nFft` taps, already pad-centred
 */
class WakeFrontend(val spec: WakeFrontendSpec, private val filterbank: DoubleArray, private val window: DoubleArray) {

    val sampleRate: Int = spec.sampleRate
    val nMels: Int = spec.nMels
    val nFft: Int = spec.nFft
    val hopLength: Int = spec.hopLength
    val nFrames: Int = spec.nFrames
    val nSamples: Int = spec.nSamples
    val nBins: Int = spec.nBins

    init {
        val problem = spec.describeMismatch()
        if (problem != null) throw IllegalStateException("Unusable wake-word front end: $problem")
        require(filterbank.size == nMels * nBins) {
            "mel filterbank is ${filterbank.size} floats, expected ${nMels * nBins}"
        }
        require(window.size == nFft) { "window is ${window.size} taps, expected $nFft" }
    }

    private val fft = Fft(nFft)
    private val frame = DoubleArray(nFft)
    private val spectrum = DoubleArray(nBins)

    private val pcenB = spec.pcen.smootherB
    private val pcenZi = spec.pcen.smootherZi
    private val pcenSeedScaled = spec.pcen.smootherInit == "scaled"
    private val pcenAlpha = spec.pcen.alpha
    private val pcenDelta = spec.pcen.delta
    private val pcenR = spec.pcen.r
    private val pcenEps = spec.pcen.eps
    private val pcenDeltaR = Math.pow(pcenDelta, pcenR)

    /**
     * One mel frame from `audio[offset .. offset + nFft)`, written into column
     * [frame] of an `nMels x nFrames` row-major buffer — `mel[m * nFrames + frame]`.
     */
    fun melFrameInto(audio: DoubleArray, offset: Int, mel: FloatArray, frame: Int, nFrames: Int) {
        fft.magnitude(audio, offset, window, spectrum)
        for (m in 0 until nMels) {
            val row = m * nBins
            var acc = 0.0
            for (k in 0 until nBins) acc += filterbank[row + k] * spectrum[k]
            mel[m * nFrames + frame] = acc.toFloat()
        }
    }

    /**
     * PCEN, transposed into model input order.
     *
     * @param mel `nMels x nFrames`, row-major, linear magnitude
     * @param out `nFrames x nMels`, row-major — the model's `(n_frames, n_mels, 1)`
     *   input, whose trailing axis needs no storage
     *
     * The smoother is reset at the start of every window, exactly as the
     * trainer's streaming extractor does by re-running normalisation over the
     * whole rolling buffer each time. Carrying the filter state across windows
     * would be cheaper and would silently disagree with the trainer.
     */
    fun pcenInto(mel: FloatArray, out: FloatArray) {
        val oneMinusB = 1.0 - pcenB
        val smooth = DoubleArray(nFrames)

        for (m in 0 until nMels) {
            val row = m * nFrames

            // scipy's `lfilter(..., zi=zi)` first step, spelled out: the seed is
            // either a bare constant or that constant times the first frame,
            // whichever this bundle's librosa used.
            var state = pcenB * mel[row] + if (pcenSeedScaled) pcenZi * mel[row] else pcenZi
            smooth[0] = state
            for (t in 1 until nFrames) {
                state = pcenB * mel[row + t] + oneMinusB * state
                smooth[t] = state
            }

            for (t in 0 until nFrames) {
                val s = mel[row + t].toDouble()
                // librosa writes the gain as exp(-alpha * (log(eps) + log1p(M/eps)))
                // rather than the algebraically equal (eps + M)^-alpha, because the
                // log1p form does not lose precision for small M. Same here.
                val gain = Math.exp(-pcenAlpha * (Math.log(pcenEps) + Math.log1p(smooth[t] / pcenEps)))
                out[t * nMels + m] = (Math.pow(s * gain + pcenDelta, pcenR) - pcenDeltaR).toFloat()
            }
        }
    }
}
