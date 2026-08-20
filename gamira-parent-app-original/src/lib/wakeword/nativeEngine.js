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
// It turns out this device's WebView cannot open `getUserMedia` at all —
// confirmed directly: a fresh page, before this service ever touches the
// microphone, still fails with `NotReadableError: Could not start audio
// source`, while native `AudioRecord` opens fine at the same moment. So the
// same microphone this file already has open for wake-word scoring doubles
// as the *conversation's* audio input too: `subscribe()` below switches the
// native service from scoring mode into a raw-PCM tap (`WakeWord.beginAudioTap`)
// and forwards each chunk as a `Float32Array`, matching exactly the shape
// `geminiVoice.js` already expects from the *web* engine's own worklet tap
// (`audioSource.subscribe`) — so nothing downstream of that callback needs to
// know which one produced the chunk, and `geminiVoice.js` never has to call
// `getUserMedia` on this platform at all.
//
// What does NOT carry over to the native path, and why that is an accepted
// trade rather than an oversight:
//
//   - `takeRecent()` always returns empty. The pre-speech ring buffer that
//     lets "Gamira, did I take my medicine?" work in one breath lives in the
//     WebView's AudioWorklet on the web build. It could be built the same way
//     the live tap above was — a small ring buffer on the native side,
//     replayed on `subscribe` — but that is additional scope beyond fixing
//     the broken microphone, not a consequence of this architecture. A person
//     using the native app hears the wake chime and then has to actually ask
//     their question, rather than having asked it already.
//   - `stream` and `captureCtx` are always null. There is no WebView
//     `MediaStream` at all on this path; `geminiVoice.js` is expected to skip
//     its own `getUserMedia` call whenever `audioSource` is provided, exactly
//     as it skips building a worklet when one is provided on the web build.
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

/** Decode the little-endian float32 bytes WakeWordBridge.emitAudioChunk sends. */
function decodePcm(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Float32Array(bytes.buffer);
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

  // Subscribers to the live audio tap — in practice just `geminiVoice.js`,
  // never more than one at a time, but a Set costs nothing and avoids ever
  // assuming that.
  const audioSubscribers = new Set();
  let audioListenerHandle = null;

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

    /**
     * Tap the live microphone as `geminiVoice.js`'s `audioSource` does on the
     * web build. Switches the native service from wake-word scoring into a
     * raw-PCM relay for as long as anything is subscribed — see the file
     * header for why this exists instead of `getUserMedia`.
     */
    subscribe(fn) {
      const first = audioSubscribers.size === 0;
      audioSubscribers.add(fn);
      if (first) WakeWord.beginAudioTap().catch((err) => fail(err));
      return () => {
        audioSubscribers.delete(fn);
        if (audioSubscribers.size === 0) WakeWord.endAudioTap().catch(() => {});
      };
    },

    /** See the file header: the pre-speech ring buffer is web-only for now. */
    takeRecent() { return new Int16Array(0); },

    sound(event, voice) { playSound(playbackCtx, event, voice); },

    // No-ops: unlike the web engine, scoring already stops the moment
    // `subscribe()` switches the service into audio-tap mode, and resumes
    // the moment the last subscriber lets go — there is no separate
    // "pause scoring but keep everything else running" state to enter here.
    pause() {},
    resume() {},

    setOptions(options) { WakeWord.setOptions(options).catch(() => {}); },

    stop() {
      if (stopped) return;
      stopped = true;
      listenerHandles.splice(0).forEach((h) => h.remove());
      audioListenerHandle?.remove();
      audioListenerHandle = null;
      audioSubscribers.clear();
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
      audioListenerHandle = await WakeWord.addListener('audio', (event) => {
        if (!event?.pcm || !audioSubscribers.size) return;
        const chunk = decodePcm(event.pcm);
        for (const fn of audioSubscribers) fn(chunk);
      });

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
