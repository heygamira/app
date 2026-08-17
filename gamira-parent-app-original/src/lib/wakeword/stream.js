// Rolling audio and mel buffers, ported from the trainer's
// `engine/feature_extractor.py::StreamingFeatureExtractor`.
//
// Recomputing all 151 mel frames on every chunk would be ~19x redundant STFT
// work for the 8 frames that are actually new. Because front end v2 is
// uncentred, every frame is a pure function of an absolute audio position, so
// only the new frames need computing and the result is identical to analysing
// the whole window offline.
//
// PCEN is still applied across the full window on every call, exactly as the
// Python does: it is a cheap IIR pass over 151x80 values, and doing it
// window-wise is what makes the detector see precisely what the trainer saw.

export class StreamingFeatures {
  /** @param {import('./frontend.js').WakeFrontend} frontend */
  constructor(frontend) {
    this.frontend = frontend;
    this.nSamples = frontend.nSamples;
    this.nMels = frontend.nMels;
    this.nFrames = frontend.nFrames;
    this.hopLength = frontend.hopLength;
    this.nFft = frontend.nFft;

    this._audio = new Float32Array(this.nSamples);
    this._mel = new Float32Array(this.nMels * this.nFrames);
    // Samples not yet consumed. The analysis window only ever advances in whole
    // hops, otherwise the audio ring and the mel ring drift apart.
    this._stage = new Float32Array(this.hopLength);
    this._staged = 0;
    this._received = 0;

    this._features = new Float32Array(this.nFrames * this.nMels);
  }

  get isBufferFull() {
    return this._received >= this.nSamples;
  }

  /** Feed mono float32 audio at the front end's sample rate. Any length. */
  pushAudio(chunk) {
    if (!chunk.length) return;
    this._received += chunk.length;

    const hop = this.hopLength;
    let offset = 0;

    // Top up the staging buffer to a whole hop first.
    if (this._staged > 0) {
      const need = hop - this._staged;
      const take = Math.min(need, chunk.length);
      this._stage.set(chunk.subarray(0, take), this._staged);
      this._staged += take;
      offset = take;
      if (this._staged < hop) return;
      this._shiftAudio(this._stage);
      this._advanceMel(1);
      this._staged = 0;
    }

    const remaining = chunk.length - offset;
    const whole = Math.floor(remaining / hop) * hop;
    if (whole > 0) {
      this._shiftAudio(chunk.subarray(offset, offset + whole));
      this._advanceMel(whole / hop);
      offset += whole;
    }

    const leftover = chunk.length - offset;
    if (leftover > 0) {
      this._stage.set(chunk.subarray(offset), 0);
      this._staged = leftover;
    }
  }

  _shiftAudio(samples) {
    const m = samples.length;
    if (m >= this.nSamples) {
      this._audio.set(samples.subarray(m - this.nSamples));
      return;
    }
    this._audio.copyWithin(0, m);
    this._audio.set(samples, this.nSamples - m);
  }

  /** Compute exactly the `k` mel frames the new audio unlocked. */
  _advanceMel(k) {
    if (k <= 0) return;
    const { nFrames, nMels, hopLength, nFft, nSamples } = this;

    if (k >= nFrames) {
      for (let t = 0; t < nFrames; t++) {
        this.frontend.melFrameInto(this._audio, t * hopLength, this._mel, t, nFrames);
      }
      return;
    }

    // Shift each mel row left by k, then fill the k newest frames. They end at
    // the buffer end, stepping back one hop each.
    for (let m = 0; m < nMels; m++) {
      const row = m * nFrames;
      this._mel.copyWithin(row, row + k, row + nFrames);
    }
    const start = nSamples - nFft - (k - 1) * hopLength;
    for (let i = 0; i < k; i++) {
      this.frontend.melFrameInto(
        this._audio, start + i * hopLength, this._mel, nFrames - k + i, nFrames
      );
    }
  }

  /**
   * The analysis window as it currently stands, in chronological order.
   *
   * Only used to check parity: the streamed features must equal a full offline
   * pass over exactly this audio. Comparing against the *current* window rather
   * than the original clip is what keeps the check independent of where the
   * chunk boundaries happened to fall.
   */
  getAudioSnapshot() {
    return this._audio.slice();
  }

  /**
   * Model input: `nFrames x nMels` float32, which is the `(n_frames, n_mels, 1)`
   * tensor the ONNX graph wants (the trailing axis needs no storage).
   *
   * Returns a buffer that is reused between calls — copy it if you need to keep
   * it past the next `getFeatures`.
   */
  getFeatures() {
    this.frontend.pcenInto(this._mel, this._features);
    return this._features;
  }

  reset() {
    this._audio.fill(0);
    this._mel.fill(0);
    this._staged = 0;
    this._received = 0;
  }
}
