// Energy gate, ported from the trainer's `engine/vad.py::VoiceGate`.
//
// Two jobs, both of which matter more in a browser than they did on a desktop:
//
//   1. Correctness — running the model on silence and pure noise is where most
//      false accepts came from.
//   2. Battery — a room is quiet most of the time, and skipping inference on
//      silence is the cheapest saving an always-on detector has. On a phone
//      this is the difference between a listening app and a warm one.
//
// A hangover keeps the gate open briefly after the energy drops, so the tail of
// a word is never clipped.
//
// The optional webrtcvad path in the Python version is not ported: it is off in
// config.yaml, and there is no equivalent in the browser worth the weight.

const SILENCE_DBFS = -120;

export function rmsDbfs(chunk) {
  if (!chunk.length) return SILENCE_DBFS;
  let sum = 0;
  for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
  const rms = Math.sqrt(sum / chunk.length);
  return rms <= 1e-10 ? SILENCE_DBFS : 20 * Math.log10(rms);
}

export class VoiceGate {
  constructor({ enabled = true, min_rms_dbfs: minRmsDbfs = -55, hangover_frames: hangoverFrames = 12 } = {}) {
    this.enabled = enabled;
    this.minRmsDbfs = minRmsDbfs;
    this.hangoverFrames = hangoverFrames;

    this._hangover = 0;
    this._level = SILENCE_DBFS;
    this._open = false;

    // Rolling noise-floor estimate, which drives the adaptive threshold.
    this._noiseFloor = -60;
    this._floorAlpha = 0.02;
  }

  /** True if inference should run for this chunk. */
  accept(chunk) {
    const level = rmsDbfs(chunk);
    this._level = level;

    // Only quiet frames update the noise floor, or speech would drag it up.
    if (level < this.minRmsDbfs) {
      this._noiseFloor += this._floorAlpha * (level - this._noiseFloor);
    }

    if (!this.enabled) {
      this._open = true;
      return true;
    }

    const active = level >= this.minRmsDbfs;
    if (active) this._hangover = this.hangoverFrames;
    else if (this._hangover > 0) this._hangover -= 1;

    this._open = active || this._hangover > 0;
    return this._open;
  }

  get levelDbfs() { return this._level; }
  get noiseFloorDbfs() { return this._noiseFloor; }
  get isOpen() { return this._open; }

  reset() {
    this._hangover = 0;
    this._open = false;
    this._noiseFloor = -60;
  }
}
