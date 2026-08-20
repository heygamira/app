// The native half of the wake word: bridges to `WakeWordPlugin`
// (`android/app/src/main/kotlin/com/gamira/parent/wakeword/`) instead of
// running `getUserMedia` + AudioWorklet + a Worker inside this WebView.
//
// Why this exists at all: Android suspends a WebView's audio the moment the
// screen goes off, so `engine.js`'s pipeline — the one this app used before,
// and still uses on the plain web build — stops listening exactly when
// somebody would want it most, after they put the phone down. The native
// side runs the identical mel/PCEN/trigger math (ported by hand from
// `frontend.js`, `stream.js`, `gate.js` and `trigger.js`, against the same
// `public/wake` bundle this build shipped) inside an Android foreground
// service, which is exempt from that suspension.
//
// What does NOT carry over to the native path, and why that is an accepted
// trade rather than an oversight:
//
//   - `takeRecent()` always returns empty. The pre-speech ring buffer that
//     lets "Gamira, did I take my medicine?" work in one breath lives in the
//     WebView's AudioWorklet on the web build; bridging raw PCM across the
//     Capacitor bridge on every chunk would cost more than the feature is
//     worth right now. A person using the native app hears the wake chime and
//     then has to actually ask their question, rather than having asked it
//     already.
//   - `stream` and `captureCtx` are always null. There is no WebView
//     `MediaStream` to hand a voice session, because the microphone is native
//     `AudioRecord` now. `useWakeWord.js`'s existing "no resources yet" path
//     already handles this — `voice.start()` opens its own `getUserMedia` the
//     first time, exactly as it does today on a cold page.
//   - `playbackCtx` is real, though: nothing about audio *output* needs to
//     leave the WebView, so the chime and Gemini's spoken replies still play
//     through a normal `AudioContext` here, warmed the same way the browser
//     engine warms its own.

import { registerPlugin, Capacitor } from '@capacitor/core';
import { playSound } from './sounds.js';

const OUTPUT_RATE = 24_000;

const WakeWord = registerPlugin('WakeWord');

/** Whether the native detector is the one to use on this platform. */
export function nativeWakeWordAvailable() {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === 'android';
}

/**
 * Start the native detector. Must be called from a user gesture, same as
 * `startWakeWordEngine` — creating and resuming `playbackCtx` needs one.
 *
 * @param {object} opts see `engine.js`'s `startWakeWordEngine` for the shape;
 *   this implements the same handle contract so `useWakeWord.js` needs no
 *   native-specific branch at all.
 */
export function startNativeWakeWordEngine({
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
  let ready = false;
  let sampleRate = 16000;
  let playbackCtx = null;
  const listenerHandles = [];

  const fail = (err) => {
    if (stopped) return;
    onError(err instanceof Error ? err : new Error(String(err)));
  };

  const handle = {
    get stream() { return null; },
    get captureCtx() { return null; },
    get playbackCtx() { return playbackCtx; },
    get sampleRate() { return sampleRate; },
    get ready() { return ready; },

    /** No raw-audio access from the native engine; nobody to tell. */
    subscribe() { return () => {}; },

    /** See the file header: the pre-speech ring buffer is web-only for now. */
    takeRecent() { return new Int16Array(0); },

    sound(event, voice) { playSound(playbackCtx, event, voice); },

    pause() { WakeWord.pause().catch(() => {}); },
    resume() { WakeWord.resume().catch(() => {}); },
    setOptions(options) { WakeWord.setOptions(options).catch(() => {}); },

    stop() {
      if (stopped) return;
      stopped = true;
      listenerHandles.splice(0).forEach((h) => h.remove());
      WakeWord.stop().catch(() => {});
      try { playbackCtx?.close(); } catch { /* ignore */ }
      playbackCtx = null;
    },
  };

  (async () => {
    try {
      listenerHandles.push(
        await WakeWord.addListener('maybe', (event) => onMaybe(event)),
        await WakeWord.addListener('detect', (event) => onDetect(event)),
        await WakeWord.addListener('release', () => onRelease()),
        await WakeWord.addListener('error', (event) => {
          fail(new Error(event?.message || 'wake word service failed'));
        }),
      );

      playbackCtx = new AudioContext({ sampleRate: OUTPUT_RATE });
      await playbackCtx.resume();
      if (stopped) return;

      const status = await WakeWord.start({ thresholdOffset, preconnectThreshold });
      if (stopped) return;
      if (status?.sampleRate) sampleRate = status.sampleRate;
      ready = true;
      onReady({ wakeWord: status?.wakeWord, threshold: status?.threshold, sampleRate });
    } catch (err) {
      fail(err);
    }
  })();

  return handle;
}
