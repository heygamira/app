// The trigger state machine, ported from the trainer's
// `engine/detector.py` (`_update_trigger_state`, `_decay`, `effective_threshold`).
//
// Rising-edge with hysteresis and a refractory window: it fires as the score
// climbs and reports the peak, rather than waiting for the score to fall back
// (which is how an earlier version of the Python ended up logging
// `confidence: 0.033 | smoothed: 0.999` — it was reporting the score *after*
// the user had stopped talking).
//
// One thing is added here that the Python has no need for: a second, lower
// threshold that says "something is happening" long before the detector is
// willing to commit. The Parent App uses it to start opening a Gemini Live
// session speculatively, so the socket is already up by the time the wake word
// is confirmed. It is deliberately part of the same hysteresis as the real
// trigger — it arms and re-arms on the same release threshold — so the two can
// never disagree about whether an utterance is still in progress.

export const MAYBE = 'maybe';
export const DETECT = 'detect';
export const RELEASE = 'release';

export class Trigger {
  /**
   * @param {object} detector the manifest's `detector` block
   * @param {object} adaptive the manifest's `adaptive_threshold` block
   * @param {object} [options]
   * @param {number} [options.preconnectThreshold] smoothed score that counts as "maybe"
   * @param {number} [options.thresholdOffset] user sensitivity nudge, added to the threshold
   */
  constructor(detector, adaptive = {}, options = {}) {
    this.threshold = detector.threshold;
    this.rawThreshold = detector.raw_threshold;
    this.releaseThreshold = detector.release_threshold;
    this.consecutiveRequired = detector.consecutive_hits;
    this.refractoryPeriod = detector.refractory_period;
    this.alpha = 2 / (detector.smoothing_window + 1);

    this.adaptiveEnabled = adaptive.enabled !== false;
    this.adaptiveMaxBoost = adaptive.max_boost ?? 0.15;

    this.preconnectThreshold = options.preconnectThreshold ?? 0.4;
    this.thresholdOffset = options.thresholdOffset ?? 0;

    this.raw = 0;
    this.ema = 0;
    this._armed = true;
    this._hits = 0;
    this._peak = 0;
    this._lastDetectionAt = 0;
    this._maybeOpen = false;
  }

  /**
   * The threshold in force right now.
   *
   * A noisy room produces more near-misses, so the bar rises with the measured
   * noise floor: -60 dBFS is a quiet room, -30 is a loud one.
   */
  effectiveThreshold(noiseFloorDbfs) {
    const base = Math.min(0.99, Math.max(0.05, this.threshold + this.thresholdOffset));
    if (!this.adaptiveEnabled) return base;
    const excess = Math.max(0, noiseFloorDbfs + 60) / 30;
    return Math.min(0.99, base + Math.min(this.adaptiveMaxBoost, this.adaptiveMaxBoost * excess));
  }

  /**
   * A new model score. Returns the event this caused, or null.
   *
   * @param {number} score raw model output
   * @param {number} noiseFloorDbfs from the voice gate
   * @param {number} now milliseconds, monotonic
   */
  push(score, noiseFloorDbfs, now) {
    this.raw = score;
    this.ema = this.alpha * score + (1 - this.alpha) * this.ema;
    return this._evaluate(noiseFloorDbfs, now);
  }

  /**
   * The gate closed, so no score was produced. Let the smoothed score fall
   * away, which is what lets the detector re-arm after an utterance.
   */
  decay(noiseFloorDbfs, now) {
    this.raw = 0;
    this.ema *= 1 - this.alpha;
    if (this.ema < this.releaseThreshold) {
      this._armed = true;
      this._hits = 0;
    }
    return this._evaluate(noiseFloorDbfs, now);
  }

  _evaluate(noiseFloorDbfs, now) {
    const threshold = this.effectiveThreshold(noiseFloorDbfs);
    let event = null;

    const above = this.ema >= threshold && this.raw >= this.rawThreshold;
    this._hits = above ? this._hits + 1 : 0;
    this._peak = Math.max(this._peak, this.ema);

    // "Maybe": far enough up the curve to be worth pre-connecting on, and this
    // utterance has not already been judged.
    if (!this._maybeOpen && this._armed && this.ema >= this.preconnectThreshold) {
      this._maybeOpen = true;
      event = { type: MAYBE, smoothed: this.ema, threshold };
    }

    if (this._armed && this._hits >= this.consecutiveRequired) {
      if (now - this._lastDetectionAt > this.refractoryPeriod * 1000) {
        this._lastDetectionAt = now;
        event = {
          type: DETECT,
          confidence: this.raw,
          smoothed: this.ema,
          peak: Math.max(this._peak, this.ema),
          threshold,
        };
      }
      this._armed = false;
      this._hits = 0;
    }

    // Re-arm only once the score has genuinely fallen away. The speculative
    // "maybe" clears on the same edge, which is the signal to abandon a
    // pre-connected session that never turned into a real one.
    if (this.ema < this.releaseThreshold) {
      if (!this._armed) {
        this._armed = true;
        this._peak = 0;
      }
      if (this._maybeOpen) {
        this._maybeOpen = false;
        if (!event) event = { type: RELEASE };
      }
    }

    return event;
  }

  reset() {
    this.raw = 0;
    this.ema = 0;
    this._armed = true;
    this._hits = 0;
    this._peak = 0;
    this._maybeOpen = false;
  }
}
