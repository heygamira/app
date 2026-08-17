// The detection loop, off the main thread.
//
// Ported from `engine/detector.py::_detection_loop`. Per chunk:
//
//   1. Gate on energy — silence never reaches the model.
//   2. Update the rolling mel buffer (only the new frames are computed).
//   3. Run ONNX inference.
//   4. Smooth, then run the trigger state machine.
//
// Why a worker and not the audio worklet: onnxruntime-web cannot run in an
// AudioWorkletGlobalScope. Why a worker and not the main thread: this screen is
// read by someone who often needs it in a hurry, and 12.5 inferences a second
// on the thread that draws it is not acceptable.

// The WASM-only entry point. The default one also pulls in the WebGPU and
// WebGL backends, which this never uses: a 3 MB model at 12.5 inferences a
// second is dominated by per-call overhead, and the GPU path costs more than it
// saves while adding a large chunk to the download.
import * as ort from 'onnxruntime-web/wasm';

import { WakeFrontend } from './frontend.js';
import { StreamingFeatures } from './stream.js';
import { VoiceGate } from './gate.js';
import { Trigger } from './trigger.js';

// Threads would need COOP/COEP cross-origin isolation on the whole app, which
// buys nothing here: the Python detector is deliberately single-threaded too
// (`intra_op_threads: 1` in config.yaml), because these matrices are small
// enough that thread coordination costs more than it saves.
ort.env.wasm.numThreads = 1;
ort.env.logLevel = 'error';
// `wasmPaths` is deliberately not set. onnxruntime-web locates its binary with
// `new URL('...wasm', import.meta.url)`, which Vite resolves at build time into
// a content-hashed asset — so it is cached immutably and there is exactly one
// copy of a 13 MB file in the build. Pointing wasmPaths at a hand-copied
// directory overrides that and ships it twice.

/** One inference per this many samples: 80 ms, matching the Python cadence. */
const INFER_EVERY = 1280;

/** How often to report the score upward. The UI cannot use 12.5 Hz. */
const REPORT_INTERVAL_MS = 100;

/**
 * When the room is quiet the gate is closed anyway, but the resampler and RMS
 * still run per chunk. Nothing to skip there — the real saving is that
 * `gate.accept` returning false means no mel, no PCEN and no inference.
 */
let frontend = null;
let features = null;
let gate = null;
let trigger = null;
let session = null;
let inputName = 'mel_input';

let paused = false;
let sinceInfer = 0;
let resampleRatio = 1;
let resampleCarry = 0;

let lastReportAt = 0;
let inferCount = 0;
let inferMs = 0;

const post = (message, transfer) => self.postMessage(message, transfer || []);

/**
 * Linear resampling to the model's rate.
 *
 * An AudioContext asked for 16 kHz normally gives 16 kHz, but the rate is a
 * hint and some devices ignore it. The trainer's own browser recorder
 * (`ui/src/lib/recorder.ts`) resamples the same way, so audio collected on a
 * device like this and audio detected on it agree.
 */
function resample(chunk) {
  if (resampleRatio === 1) return chunk;
  const outLength = Math.floor((chunk.length - resampleCarry) / resampleRatio);
  if (outLength <= 0) {
    resampleCarry -= chunk.length;
    return new Float32Array(0);
  }
  const out = new Float32Array(outLength);
  let pos = resampleCarry;
  for (let i = 0; i < outLength; i++) {
    const index = Math.floor(pos);
    const frac = pos - index;
    const a = chunk[index];
    const b = index + 1 < chunk.length ? chunk[index + 1] : a;
    out[i] = a + (b - a) * frac;
    pos += resampleRatio;
  }
  resampleCarry = pos - chunk.length;
  return out;
}

async function init(payload) {
  const { spec, filterbank, window, manifest, sampleRate, options } = payload;

  frontend = new WakeFrontend(spec, new Float32Array(filterbank), new Float32Array(window));
  features = new StreamingFeatures(frontend);
  gate = new VoiceGate(manifest.vad);
  trigger = new Trigger(manifest.detector, manifest.adaptive_threshold, options);

  resampleRatio = sampleRate / frontend.sampleRate;
  resampleCarry = 0;

  session = await ort.InferenceSession.create(manifest.modelUrl, {
    executionProviders: ['wasm'],
    graphOptimizationLevel: 'all',
  });
  inputName = session.inputNames?.[0] || 'mel_input';

  // One warm inference so the first real one is not the one that pays for
  // compiling the graph — that cost would land exactly on the wake word.
  const warm = new ort.Tensor(
    'float32', new Float32Array(frontend.nFrames * frontend.nMels),
    [1, frontend.nFrames, frontend.nMels, 1]
  );
  await session.run({ [inputName]: warm });

  post({
    type: 'ready',
    version: manifest.version,
    wakeWord: manifest.wake_word,
    threshold: trigger.threshold,
    sampleRate: frontend.sampleRate,
    resampling: resampleRatio !== 1 ? sampleRate : null,
  });
}

async function onAudio(buffer) {
  if (!session || paused) return;

  const chunk = resample(new Float32Array(buffer));
  if (!chunk.length) return;

  const now = performance.now();

  if (!gate.accept(chunk)) {
    // Silence never reaches the model: fewer false accepts, and on a phone this
    // is where nearly all the battery saving comes from.
    const event = trigger.decay(gate.noiseFloorDbfs, now);
    if (event) post(event);
    report(now, false);
    return;
  }

  features.pushAudio(chunk);
  if (!features.isBufferFull) {
    // Nothing to score yet, and no credit to bank for it either.
    sinceInfer = 0;
    return;
  }
  sinceInfer += chunk.length;
  if (sinceInfer < INFER_EVERY) return;
  // Carry the remainder rather than zeroing it. The worklet delivers 800
  // samples and the model wants one look per 1280, so zeroing would round every
  // interval up to two chunks — 10 inferences a second instead of 12.5. That is
  // 20% fewer looks at the wake word while it is inside the window, and the
  // smoothed score has that much less chance to climb past the threshold before
  // the word is gone.
  //
  // Capped below one full interval so a stall cannot bank enough credit to come
  // back and run a burst of catch-up inferences on stale audio.
  sinceInfer = Math.min(sinceInfer - INFER_EVERY, INFER_EVERY - 1);

  const started = performance.now();
  const input = new ort.Tensor(
    'float32', features.getFeatures().slice(),
    [1, frontend.nFrames, frontend.nMels, 1]
  );
  const output = await session.run({ [inputName]: input });
  const score = Object.values(output)[0].data[0];
  inferMs += performance.now() - started;
  inferCount += 1;

  const event = trigger.push(score, gate.noiseFloorDbfs, performance.now());
  if (event) post(event);
  report(performance.now(), true);
}

function report(now, gateOpen) {
  if (now - lastReportAt < REPORT_INTERVAL_MS) return;
  lastReportAt = now;
  post({
    type: 'score',
    raw: trigger.raw,
    ema: trigger.ema,
    threshold: trigger.effectiveThreshold(gate.noiseFloorDbfs),
    preconnectThreshold: trigger.preconnectThreshold,
    levelDbfs: gate.levelDbfs,
    noiseFloorDbfs: gate.noiseFloorDbfs,
    gateOpen,
    inferCount,
    avgInferMs: inferCount ? inferMs / inferCount : 0,
  });
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    switch (message.type) {
      case 'init':
        await init(message);
        break;
      case 'audio':
        await onAudio(message.buffer);
        break;
      case 'pause':
        // Held open rather than torn down: a live voice session owns the
        // conversation, but it ends, and re-creating the ORT session would cost
        // a second of silence right when the user might speak again.
        paused = true;
        trigger.reset();
        features.reset();
        gate.reset();
        break;
      case 'resume':
        paused = false;
        break;
      case 'options':
        if (typeof message.thresholdOffset === 'number') {
          trigger.thresholdOffset = message.thresholdOffset;
        }
        if (typeof message.preconnectThreshold === 'number') {
          trigger.preconnectThreshold = message.preconnectThreshold;
        }
        break;
      default:
        break;
    }
  } catch (err) {
    post({ type: 'error', message: err?.message || String(err) });
  }
};
