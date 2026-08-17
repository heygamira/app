// The wake-word audio front end, ported from the trainer's
// `utils/audio_utils.py::Frontend`.
//
// This must produce the same numbers that file produces. A PCEN-trained model
// fed anything else loads cleanly, runs at full speed, and never fires — there
// is no error to see, only a detector that has quietly stopped working. Two
// deliberate choices keep that from happening:
//
//   1. The mel filterbank and the analysis window are NOT computed here. They
//      are shipped as float32 blobs by `python main.py export-web`, taken
//      straight off the Python `Frontend` instance. Librosa's mel filterbank
//      uses the Slaney mel scale *and* Slaney area normalisation; re-deriving
//      that here is exactly the kind of near-miss that would cost days.
//   2. `npm run wake:parity` replays golden vectors from the same export
//      through this file and asserts the features match. Run it after every
//      retrain.
//
// Front end v2 only: magnitude mel (power = 1), `center = false`, PCEN. The
// uncentred framing is what makes every frame a pure function of an absolute
// audio position, which is what lets `stream.js` compute only the new ones.

import { createRfft } from './rfft.js';

export const SUPPORTED_FRONTEND_VERSION = 2;

/**
 * Frame `t` covers `audio[t*hop .. t*hop + nFft)`, so a window of `nFrames`
 * needs this many samples. Mirrors `spec_n_samples`.
 */
export function specSampleCount(spec) {
  if (spec.center) return (spec.n_frames - 1) * spec.hop_length;
  return spec.n_fft + (spec.n_frames - 1) * spec.hop_length;
}

/**
 * Why this bundle cannot be used, or null if it can.
 *
 * Deliberately loud and specific: the Python side refuses to activate a model
 * whose front-end spec is missing, for the same reason.
 */
export function describeSpecMismatch(spec) {
  if (!spec || typeof spec !== 'object') return 'the front-end spec is missing';
  if (spec.version !== SUPPORTED_FRONTEND_VERSION) {
    return `this build implements front end v${SUPPORTED_FRONTEND_VERSION}, the model wants v${spec.version}`;
  }
  if (spec.center) return 'center=true is not supported (v2 models are uncentred)';
  if (spec.power !== 1) return `power=${spec.power} is not supported (v2 uses magnitude)`;
  if (spec.normalization !== 'pcen') return `normalization=${spec.normalization} is not supported`;
  if (!spec.pcen) return 'the spec claims PCEN but carries no PCEN parameters';
  const smoother = spec.pcen.smoother;
  if (!smoother) {
    return 'the bundle predates the resolved PCEN smoother; re-run `python main.py export-web`';
  }
  if (smoother.init !== 'constant' && smoother.init !== 'scaled') {
    return `unknown PCEN initialisation "${smoother.init}"`;
  }
  return null;
}

export class WakeFrontend {
  /**
   * @param {object} spec parsed frontend.json
   * @param {Float32Array} filterbank `n_mels x (n_fft/2 + 1)`, row-major
   * @param {Float32Array} window `n_fft` taps, already pad-centred
   */
  constructor(spec, filterbank, window) {
    const problem = describeSpecMismatch(spec);
    if (problem) throw new Error(`Unusable wake-word front end: ${problem}`);

    this.spec = spec;
    this.sampleRate = spec.sample_rate;
    this.nMels = spec.n_mels;
    this.nFft = spec.n_fft;
    this.hopLength = spec.hop_length;
    this.nFrames = spec.n_frames;
    this.nSamples = specSampleCount(spec);
    this.nBins = spec.n_fft / 2 + 1;

    if (filterbank.length !== this.nMels * this.nBins) {
      throw new Error(
        `mel filterbank is ${filterbank.length} floats, expected ${this.nMels * this.nBins}`
      );
    }
    if (window.length !== this.nFft) {
      throw new Error(`window is ${window.length} taps, expected ${this.nFft}`);
    }
    this.filterbank = filterbank;
    this.window = window;

    // The smoother coefficient and its seed are resolved by the exporter, not
    // recomputed here. librosa has shipped two different PCEN initialisations:
    // one seeds the integrator with the first frame, the current one seeds it
    // with the filter's steady-state gain as a bare constant. With mel
    // magnitudes around 0.005 that constant dominates the entire window, so
    // guessing wrong does not look wrong — it just produces a detector that
    // never fires. `python main.py export-web` decides by experiment and writes
    // the answer into frontend.json.
    const p = spec.pcen;
    this.pcenB = p.smoother.b;
    this.pcenZi = p.smoother.zi;
    this.pcenSeedScaled = p.smoother.init === 'scaled';
    this.pcenAlpha = p.alpha;
    this.pcenDelta = p.delta;
    this.pcenR = p.r;
    this.pcenEps = p.eps;
    this.pcenDeltaR = Math.pow(p.delta, p.r);

    this._rfft = createRfft(this.nFft);
    this._spectrum = new Float64Array(this.nBins);
    this._smooth = new Float64Array(this.nFrames);
  }

  /**
   * One mel frame from `audio[offset .. offset + nFft)`.
   *
   * Written into `mel` at column `frame` of an `nMels x nFrames` row-major
   * buffer, which is the layout `(n_mels, time)` has in the Python code.
   */
  melFrameInto(audio, offset, mel, frame, nFrames) {
    this._rfft(audio, offset, this.window, this._spectrum);
    const spectrum = this._spectrum;
    const fb = this.filterbank;
    const bins = this.nBins;
    for (let m = 0; m < this.nMels; m++) {
      const row = m * bins;
      let acc = 0;
      for (let k = 0; k < bins; k++) acc += fb[row + k] * spectrum[k];
      mel[m * nFrames + frame] = acc;
    }
  }

  /**
   * PCEN, transposed into model input order.
   *
   * @param {Float32Array} mel `nMels x nFrames`, row-major, linear magnitude
   * @param {Float32Array} out `nFrames x nMels`, row-major — the model's
   *   `(n_frames, n_mels, 1)` input, whose trailing axis needs no storage
   *
   * The smoother is reset at the start of every window, exactly as
   * `StreamingFeatureExtractor.get_features` does by re-running `normalize`
   * over the whole rolling buffer each time. Carrying the filter state across
   * windows would be cheaper and would silently disagree with the trainer.
   */
  pcenInto(mel, out) {
    const { nMels, nFrames, pcenB, pcenAlpha, pcenDelta, pcenR, pcenEps, pcenDeltaR } = this;
    const smooth = this._smooth;
    const oneMinusB = 1 - pcenB;

    const { pcenZi, pcenSeedScaled } = this;

    for (let m = 0; m < nMels; m++) {
      const row = m * nFrames;

      // scipy's `lfilter(..., zi=zi)` first step, spelled out: the seed is
      // either a bare constant or that constant times the first frame,
      // whichever this bundle's librosa used.
      let state = pcenB * mel[row] + (pcenSeedScaled ? pcenZi * mel[row] : pcenZi);
      smooth[0] = state;
      for (let t = 1; t < nFrames; t++) {
        state = pcenB * mel[row + t] + oneMinusB * state;
        smooth[t] = state;
      }

      for (let t = 0; t < nFrames; t++) {
        const s = mel[row + t];
        // librosa writes the gain as exp(-alpha * (log(eps) + log1p(M/eps)))
        // rather than the algebraically equal (eps + M)^-alpha, because the
        // log1p form does not lose precision for small M. Same here.
        const gain = Math.exp(-pcenAlpha * (Math.log(pcenEps) + Math.log1p(smooth[t] / pcenEps)));
        out[t * nMels + m] = Math.pow(s * gain + pcenDelta, pcenR) - pcenDeltaR;
      }
    }
  }

  /**
   * The whole pipeline for one exact-length window. Used by the parity check;
   * the live path goes through `stream.js`, which computes only new frames.
   *
   * @param {Float32Array} audio exactly `nSamples` samples
   * @returns {Float32Array} `nFrames x nMels`
   */
  features(audio) {
    if (audio.length !== this.nSamples) {
      throw new Error(`expected ${this.nSamples} samples, got ${audio.length}`);
    }
    const mel = new Float32Array(this.nMels * this.nFrames);
    for (let t = 0; t < this.nFrames; t++) {
      this.melFrameInto(audio, t * this.hopLength, mel, t, this.nFrames);
    }
    const out = new Float32Array(this.nFrames * this.nMels);
    this.pcenInto(mel, out);
    return out;
  }
}
