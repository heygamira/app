// The always-on half of the wake word: microphone, worklet, worker, ring buffer.
//
// This owns every resource a voice session used to acquire for itself, which is
// the whole reason the Live API gap can be hidden. By the time the wake word
// fires, the microphone is open, both AudioContexts are running, the ONNX
// session is warm and the ~400 kB @google/genai chunk is already resident —
// none of that is left on the critical path.
//
// Two constraints worth knowing before changing anything here:
//
//   * The AudioContext can only be created and resumed inside a user gesture.
//     `arm()` must be called from a click handler, once per app session.
//   * A backgrounded tab suspends the AudioContext. There is no service worker
//     in this app, so "always on" means "while the app is open and in front".
//     Real always-on listening needs the native app.

import { loadWakeBundle } from './bundle.js';
import { playSound } from './sounds.js';

const OUTPUT_RATE = 24_000;
const TARGET_RATE = 16_000;

/** How much audio to keep so the utterance survives the connection delay. */
const RING_SECONDS = 3;

/**
 * The microphone constraints.
 *
 * Deliberately the *processed* stream, matching what `geminiVoice.js` has
 * always asked for: without echo cancellation Gemini hears itself through the
 * speaker and interrupts itself in a loop, and the wake word and the voice
 * session share one stream so there is one choice to make.
 *
 * Note this differs from how the training data is collected — the trainer's
 * recorder turns all three off to capture raw microphone audio. PCEN normalises
 * level, which covers the gain control, but noise suppression genuinely alters
 * the spectrum. If on-device recall turns out much worse than the offline
 * numbers, that is the first thing to suspect, and the fix is either to collect
 * a slice of training data through a processed stream or to set
 * SHARE_STREAM_WITH_VOICE to false below.
 */
const MIC_CONSTRAINTS = {
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

/**
 * Whether the voice session reuses the wake word's microphone.
 *
 * True is the fast path and what makes activation feel instant. Setting it to
 * false gives the detector its own raw, unprocessed stream at the cost of a
 * second `getUserMedia` — which is only worth paying if the shared processed
 * stream measurably hurts detection.
 */
export const SHARE_STREAM_WITH_VOICE = true;

/** Batches mic samples on the audio thread. Float32; consumers convert. */
const CAPTURE_WORKLET = `
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    // ~50ms per message. Every millisecond spent batching here is a millisecond
    // added to how long Gamira takes to start replying, so this is kept short;
    // it is still coarse enough not to flood the main thread. At 16 kHz it is
    // also exactly five 160-sample hops, so the detector's rolling buffer
    // advances in whole frames.
    this._target = Math.round(sampleRate / 20);
    this._chunks = [];
    this._length = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    this._chunks.push(new Float32Array(channel));
    this._length += channel.length;
    if (this._length < this._target) return true;

    const merged = new Float32Array(this._length);
    let offset = 0;
    for (const chunk of this._chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    this._chunks = [];
    this._length = 0;

    this.port.postMessage(merged, [merged.buffer]);
    return true;
  }
}
registerProcessor('pcm-capture', PCMCapture);
`;

export function floatToPcm16(input) {
  const pcm = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

/**
 * Start the detector. Must be called from a user gesture.
 *
 * @param {object} opts
 * @param {(event: object) => void} [opts.onDetect]   the wake word was confirmed
 * @param {(event: object) => void} [opts.onMaybe]    might be the wake word; pre-connect
 * @param {() => void} [opts.onRelease]               the maybe came to nothing
 * @param {(state: object) => void} [opts.onScore]    telemetry, ~10 Hz
 * @param {(info: object) => void} [opts.onReady]
 * @param {(err: Error) => void} [opts.onError]
 * @param {number} [opts.thresholdOffset]
 * @param {number} [opts.preconnectThreshold]
 */
export function startWakeWordEngine({
  onDetect = () => {},
  onMaybe = () => {},
  onRelease = () => {},
  onScore = () => {},
  onReady = () => {},
  onError = () => {},
  thresholdOffset = 0,
  preconnectThreshold = 0.4,
} = {}) {
  let stopped = false;
  let stream = null;
  let captureCtx = null;
  let playbackCtx = null;
  let workletUrl = null;
  let sourceNode = null;
  let workletNode = null;
  let sinkNode = null;
  let worker = null;
  let ready = false;
  // Whether the owner has asked for scoring to stop. Latched rather than sent
  // and forgotten: the engine takes a moment to load, and a pause that arrives
  // in that window would otherwise be dropped on the floor — leaving the
  // detector scoring right through a live conversation, where the loudest thing
  // in the room is Gamira's own voice.
  let pauseRequested = false;

  // Rolling PCM, so the words spoken while the session is still connecting are
  // not lost. Sized at construction, once the real sample rate is known.
  let ring = null;
  let ringWrite = 0;
  let ringFilled = 0;
  let ringRate = TARGET_RATE;

  const subscribers = new Set();

  const fail = (err) => {
    if (stopped) return;
    const error = err instanceof Error ? err : new Error(String(err));
    cleanup();
    onError(error);
  };

  function cleanup() {
    stopped = true;
    subscribers.clear();
    try { worker?.terminate(); } catch { /* already gone */ }
    worker = null;
    try { workletNode?.disconnect(); } catch { /* ignore */ }
    try { sinkNode?.disconnect(); } catch { /* ignore */ }
    try { sourceNode?.disconnect(); } catch { /* ignore */ }
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    try { captureCtx?.close(); } catch { /* ignore */ }
    try { playbackCtx?.close(); } catch { /* ignore */ }
    captureCtx = null;
    playbackCtx = null;
    if (workletUrl) URL.revokeObjectURL(workletUrl);
    workletUrl = null;
  }

  function pushRing(chunk) {
    if (!ring) return;
    const n = Math.min(chunk.length, ring.length);
    const tail = ring.length - ringWrite;
    if (n <= tail) {
      ring.set(chunk.subarray(chunk.length - n), ringWrite);
    } else {
      ring.set(chunk.subarray(chunk.length - n, chunk.length - n + tail), ringWrite);
      ring.set(chunk.subarray(chunk.length - n + tail), 0);
    }
    ringWrite = (ringWrite + n) % ring.length;
    ringFilled = Math.min(ring.length, ringFilled + n);
  }

  const handle = {
    /** The shared microphone, or null before the engine is ready. */
    get stream() { return stream; },
    get captureCtx() { return captureCtx; },
    get playbackCtx() { return playbackCtx; },
    get sampleRate() { return ringRate; },
    get ready() { return ready; },

    /**
     * Receive every mic chunk as Float32 at the capture rate.
     * Returns an unsubscribe function.
     */
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },

    /**
     * The last `seconds` of audio, oldest first, as PCM16.
     *
     * This is what makes "Gamira, did I take my medicine?" work in one breath:
     * the question is spoken while the socket is still opening, and would
     * otherwise be gone by the time anyone is listening.
     */
    takeRecent(seconds) {
      if (!ring) return new Int16Array(0);
      const want = Math.min(ringFilled, Math.floor(seconds * ringRate));
      if (want <= 0) return new Int16Array(0);
      const out = new Float32Array(want);
      const start = (ringWrite - want + ring.length) % ring.length;
      const tail = ring.length - start;
      if (want <= tail) {
        out.set(ring.subarray(start, start + want));
      } else {
        out.set(ring.subarray(start));
        out.set(ring.subarray(0, want - tail), tail);
      }
      return floatToPcm16(out);
    },

    /**
     * Make one of Gamira's sounds, on the already-running playback context.
     *
     * The wake sound is the piece that actually makes the remaining connection
     * latency tolerable. Acknowledging within 50 ms is what every voice
     * assistant relies on, and it costs nothing here: no asset, no fetch, no
     * decode — see `sounds.js`.
     *
     * @param {'wake' | 'stopped' | 'unavailable'} event
     * @param {import('./sounds.js').WakeSound} [voice]
     */
    sound(event, voice) {
      playSound(playbackCtx, event, voice);
    },

    /** Stop scoring but keep every resource warm. Used while a session is live. */
    pause() {
      pauseRequested = true;
      worker?.postMessage({ type: 'pause' });
    },
    resume() {
      pauseRequested = false;
      worker?.postMessage({ type: 'resume' });
    },

    setOptions(options) { worker?.postMessage({ type: 'options', ...options }); },

    stop() {
      if (stopped) return;
      cleanup();
    },
  };

  (async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('This browser cannot access the microphone.');
      }

      const bundle = await loadWakeBundle();

      stream = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS });
      if (stopped) return;

      captureCtx = new AudioContext({ sampleRate: TARGET_RATE });
      playbackCtx = new AudioContext({ sampleRate: OUTPUT_RATE });
      await captureCtx.resume();
      await playbackCtx.resume();
      if (stopped) return;

      ringRate = Math.round(captureCtx.sampleRate);
      ring = new Float32Array(RING_SECONDS * ringRate);

      // Warm the voice SDK now rather than after the wake word. It is the
      // single largest chunk in the app and it is pure dead time if it loads on
      // the critical path.
      import('@google/genai').catch(() => {});

      worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
      worker.onmessage = (event) => {
        const message = event.data;
        switch (message.type) {
          case 'ready':
            ready = true;
            // Apply anything asked for while this was still loading.
            if (pauseRequested) worker?.postMessage({ type: 'pause' });
            onReady(message);
            break;
          case 'score': onScore(message); break;
          case 'maybe': onMaybe(message); break;
          case 'detect': onDetect(message); break;
          case 'release': onRelease(); break;
          case 'error': fail(new Error(message.message)); break;
          default: break;
        }
      };
      worker.onerror = (event) => fail(new Error(event.message || 'wake word worker failed'));

      worker.postMessage({
        type: 'init',
        spec: bundle.spec,
        filterbank: bundle.filterbank.buffer,
        window: bundle.window.buffer,
        manifest: {
          ...bundle.manifest,
          modelUrl: new URL(bundle.modelUrl, self.location.origin).href,
        },
        sampleRate: ringRate,
        options: { thresholdOffset, preconnectThreshold },
      }, [bundle.filterbank.buffer, bundle.window.buffer]);

      workletUrl = URL.createObjectURL(
        new Blob([CAPTURE_WORKLET], { type: 'application/javascript' })
      );
      await captureCtx.audioWorklet.addModule(workletUrl);
      if (stopped) return;

      sourceNode = captureCtx.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(captureCtx, 'pcm-capture');
      workletNode.port.onmessage = (event) => {
        if (stopped) return;
        /** @type {Float32Array} */
        const chunk = event.data;
        pushRing(chunk);
        for (const fn of subscribers) fn(chunk);
        // Nothing to score while paused, and this runs during playback — the
        // copy and the transfer are main-thread work competing with the audio
        // scheduler for no benefit.
        if (pauseRequested) return;
        // A copy, because the subscribers above still hold the original and a
        // transferred buffer would be detached out from under them.
        const copy = chunk.slice();
        worker?.postMessage({ type: 'audio', buffer: copy.buffer }, [copy.buffer]);
      };
      sourceNode.connect(workletNode);

      // The worklet produces no output, but Chrome only pulls from nodes that
      // reach the destination. A muted gain node keeps the graph alive without
      // routing the microphone back to the speakers.
      sinkNode = captureCtx.createGain();
      sinkNode.gain.value = 0;
      workletNode.connect(sinkNode);
      sinkNode.connect(captureCtx.destination);
    } catch (err) {
      fail(err);
    }
  })();

  return handle;
}
