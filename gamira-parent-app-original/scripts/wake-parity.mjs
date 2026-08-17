// Does the browser's wake-word front end still agree with the trainer's?
//
// `python main.py export-web` ships golden vectors next to the model: audio in,
// and the features and score the Python pipeline produced from it. This replays
// them through `src/lib/wakeword/frontend.js` and fails if they have drifted.
//
// Run it after every retrain, and first of all when the detector "mysteriously
// stops firing" — a PCEN model given the wrong features does not error, it just
// scores near zero on everything forever.
//
//   npm run wake:parity
//
// There is no test runner in this app and this does not need one.

import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { WakeFrontend } from '../src/lib/wakeword/frontend.js';
import { StreamingFeatures } from '../src/lib/wakeword/stream.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const WAKE_DIR = resolve(HERE, '..', 'public', 'wake');

// The front end is float32 end to end and the FFT is a different implementation
// on each side, so exact equality is not the bar. 1e-3 is far tighter than any
// difference that could change a detection and far looser than implementation
// noise.
const FEATURE_TOLERANCE = 1e-3;
const SCORE_TOLERANCE = 1e-3;

const b64 = (s) => new Uint8Array(Buffer.from(s, 'base64'));

function asFloat32(bytes) {
  return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}

function fail(message) {
  console.error(`\n  FAIL  ${message}\n`);
  process.exit(1);
}

async function loadOnnxRuntime() {
  // Optional: the feature check is what actually catches front-end drift. The
  // score check additionally proves the tensor layout handed to the model is
  // right, which is worth having when it is available.
  try {
    const ort = await import('onnxruntime-node');
    return { ort: ort.default ?? ort, name: 'onnxruntime-node' };
  } catch {
    /* not installed */
  }
  try {
    const ort = await import('onnxruntime-web/wasm');
    const runtime = ort.default ?? ort;
    runtime.env.wasm.numThreads = 1;
    // In a browser the runtime fetches its own binary; Node's fetch will not
    // touch a file:// URL, so hand it over directly. This is a detail of
    // running the browser build under Node, not something the app does.
    runtime.env.wasm.wasmBinary = (
      await readFile(
        resolve(HERE, '..', 'node_modules', 'onnxruntime-web', 'dist',
          'ort-wasm-simd-threaded.wasm')
      )
    ).buffer;
    return { ort: runtime, name: 'onnxruntime-web' };
  } catch {
    return null;
  }
}

async function main() {
  if (!existsSync(join(WAKE_DIR, 'manifest.json'))) {
    fail(
      `No bundle at ${WAKE_DIR}.\n        Export one from the wake-word project:\n` +
        `          python main.py export-web --out "${WAKE_DIR}"`
    );
  }

  const manifest = JSON.parse(await readFile(join(WAKE_DIR, 'manifest.json'), 'utf8'));
  const spec = JSON.parse(await readFile(join(WAKE_DIR, manifest.frontend), 'utf8'));
  const filterbank = asFloat32(await readFile(join(WAKE_DIR, manifest.filterbank)));
  const window = asFloat32(await readFile(join(WAKE_DIR, manifest.window)));
  const parity = JSON.parse(await readFile(join(WAKE_DIR, manifest.parity), 'utf8'));

  console.log(`\n  bundle    ${manifest.version}  (${manifest.wake_word})`);
  console.log(`  frontend  v${spec.version} ${spec.normalization}, ${spec.n_frames}x${spec.n_mels} @ ${spec.sample_rate} Hz`);
  console.log(`  threshold ${manifest.detector.threshold} (${manifest.detector.threshold_source})`);

  const frontend = new WakeFrontend(spec, filterbank, window);

  const runtime = await loadOnnxRuntime();
  let session = null;
  if (runtime) {
    try {
      session = await runtime.ort.InferenceSession.create(
        new Uint8Array(await readFile(join(WAKE_DIR, manifest.model)))
      );
      console.log(`  runtime   ${runtime.name}`);
    } catch (err) {
      console.log(`  runtime   ${runtime.name} could not load the model (${err.message})`);
    }
  } else {
    console.log('  runtime   none installed — checking features only');
  }
  console.log('');

  let failures = 0;

  for (const testCase of parity.cases) {
    const pcm = new Int16Array(b64(testCase.audio_i16).buffer);
    const audio = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) audio[i] = pcm[i] / 32768;

    const expected = asFloat32(b64(testCase.features));
    const actual = frontend.features(audio);

    if (actual.length !== expected.length) {
      console.error(`  ${testCase.name}: got ${actual.length} features, expected ${expected.length}`);
      failures += 1;
      continue;
    }

    let maxDiff = 0;
    let worstAt = -1;
    for (let i = 0; i < expected.length; i++) {
      const diff = Math.abs(actual[i] - expected[i]);
      if (diff > maxDiff) {
        maxDiff = diff;
        worstAt = i;
      }
    }

    const featuresOk = maxDiff < FEATURE_TOLERANCE;
    if (!featuresOk) failures += 1;

    const frame = Math.floor(worstAt / spec.n_mels);
    const mel = worstAt % spec.n_mels;
    console.log(
      `  ${featuresOk ? 'ok  ' : 'FAIL'}  ${testCase.name.padEnd(46)} ` +
        `features max diff ${maxDiff.toExponential(2)}` +
        (featuresOk ? '' : `  at frame ${frame}, mel ${mel} ` +
          `(python ${expected[worstAt].toFixed(6)}, js ${actual[worstAt].toFixed(6)})`)
    );

    if (!session) continue;

    const Tensor = runtime.ort.Tensor;
    const output = await session.run({
      mel_input: new Tensor('float32', actual, [1, spec.n_frames, spec.n_mels, 1]),
    });
    const score = Object.values(output)[0].data[0];
    const scoreDiff = Math.abs(score - testCase.score);
    const scoreOk = scoreDiff < SCORE_TOLERANCE;
    if (!scoreOk) failures += 1;
    console.log(
      `  ${scoreOk ? 'ok  ' : 'FAIL'}  ${''.padEnd(46)} ` +
        `score ${score.toFixed(6)} vs python ${testCase.score.toFixed(6)} (diff ${scoreDiff.toExponential(2)})`
    );
  }

  // The live detector does not call `features()` — it keeps rolling audio and
  // mel buffers and recomputes only the frames each chunk unlocked. That is a
  // second implementation of the same maths, and a drift in it would be just as
  // invisible. Mirrors the trainer's own tests/test_feature_parity.py.
  console.log('');
  for (const chunkSize of [800, 160, 1280, 2000]) {
    const stream = new StreamingFeatures(frontend);
    // Well past one window, so the buffer holds only real audio.
    const total = frontend.nSamples * 3;
    const audio = new Float32Array(total);
    for (let i = 0; i < total; i++) {
      const t = i / spec.sample_rate;
      audio[i] =
        0.3 *
        (Math.sin(2 * Math.PI * 120 * t) +
          Math.sin(2 * Math.PI * 810 * t) / 2 +
          Math.sin(2 * Math.PI * 3400 * t) / 3) *
        (0.5 + 0.5 * Math.sin(2 * Math.PI * 3.1 * t));
    }
    for (let i = 0; i < total; i += chunkSize) {
      stream.pushAudio(audio.subarray(i, Math.min(i + chunkSize, total)));
    }

    const streamed = stream.getFeatures().slice();
    const offline = frontend.features(stream.getAudioSnapshot());
    let maxDiff = 0;
    for (let i = 0; i < offline.length; i++) {
      maxDiff = Math.max(maxDiff, Math.abs(streamed[i] - offline[i]));
    }
    const ok = maxDiff < FEATURE_TOLERANCE;
    if (!ok) failures += 1;
    console.log(
      `  ${ok ? 'ok  ' : 'FAIL'}  ${`streaming vs offline, ${chunkSize}-sample chunks`.padEnd(46)} ` +
        `max diff ${maxDiff.toExponential(2)}`
    );
  }

  if (failures) {
    fail(
      `${failures} check(s) failed.\n` +
        '        The browser detector will not fire correctly until this passes.\n' +
        '        Compare src/lib/wakeword/frontend.js against\n' +
        '        the trainer\'s utils/audio_utils.py::Frontend.'
    );
  }
  console.log('\n  All parity checks passed.\n');
}

main().catch((err) => fail(err.stack || err.message));
