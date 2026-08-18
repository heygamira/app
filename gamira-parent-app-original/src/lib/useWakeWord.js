import { useCallback, useEffect, useRef, useState } from 'react';

import { startWakeWordEngine } from '@/lib/wakeword/engine.js';
import { getSettings } from '@/lib/userSettings';

// Speculation is cheap but not free, and the detector guesses far more often
// than anyone speaks — on the current model it pre-connects on most hard
// negatives too. These are what keep a noisy room from minting tokens in a loop.
const MIN_ATTEMPT_GAP_MS = 3000;
const MAX_ATTEMPTS_PER_MINUTE = 6;
/** How long a maybe has to become a yes before it is dropped. */
const ABANDON_AFTER_MS = 2000;

/**
 * Hands-free activation: listen for "Gamira" and open a voice session.
 *
 * Two engines, in order of preference:
 *
 * - **onnx** — the trained detector from the Gamira wake-word project, running
 *   locally on onnxruntime-web. Nothing leaves the device unless the wake word
 *   is actually heard.
 * - **speech** — the browser's `SpeechRecognition`, which is what this app used
 *   before. It works only on Chrome and WebKit, and it streams every word
 *   spoken in the room to Google's ASR whether or not anyone said "Gamira". It
 *   is kept as a fallback because the trained model is still being improved,
 *   and because some devices will not run the WASM build.
 *
 * ## Hiding the Live API's startup cost
 *
 * Opening a voice session means a backend round trip to mint a token, a
 * WebSocket handshake, and — on a cold page — a ~400 kB SDK download. Doing all
 * of that after the wake word means a second or more of silence, which reads as
 * "it didn't hear me" and makes people repeat themselves.
 *
 * So the session is opened *before* the detector is sure:
 *
 *   score ≥ preconnect (0.40)   →  connect, provisionally, sending nothing
 *   score ≥ threshold  (0.94)   →  chime, replay the ring buffer, start streaming
 *   neither, within 2s          →  drop it; the person never knew
 *
 * The ring buffer is what makes "Gamira, did I take my medicine?" work in one
 * breath: the question is spoken while the socket is still opening, and is
 * replayed the moment it is up.
 *
 * @param {object} voice the `useGeminiVoice` handle this should drive
 * @param {object} [options]
 * @param {string} [options.lang] BCP-47 tag for the SpeechRecognition fallback
 * @param {boolean} [options.telemetry] publish live scores as React state.
 *   Off by default: the detector reports about ten times a second, and turning
 *   that into a re-render of the home screen ten times a second — on a phone,
 *   for as long as the app is open — is not worth paying for something only the
 *   debug overlay reads.
 */
export function useWakeWord(voice, { lang = 'en-US', telemetry: wantTelemetry = false } = {}) {
  const [engine, setEngine] = useState('off');
  const [armed, setArmed] = useState(false);
  const [error, setError] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  // Read once. localStorage is not reactive, and a setting that changed
  // mid-session would want a deliberate re-arm anyway.
  const [enabled] = useState(() => getSettings().wakeWord?.enabled !== false);

  const engineRef = useRef(null);
  const recognitionRef = useRef(null);
  // Set when arming failed for a reason trying again will not fix — the
  // microphone was denied, or there is no usable engine. Without this, the
  // automatic arm below would re-prompt on every single tap.
  const blockedRef = useRef(false);
  // The hook is rebuilt on every render of the page that owns it; the engine is
  // built once, so its callbacks read the moving parts through refs.
  const voiceRef = useRef(voice);
  voiceRef.current = voice;

  // Speculation bookkeeping. The detector pre-connects far more often than
  // anyone speaks, so this is what keeps it from hammering the backend.
  const pendingRef = useRef(null);
  const recentAttemptsRef = useRef([]);
  const statsRef = useRef({
    preconnect: 0, confirm: 0, abandon: 0, throttled: 0, lastLatencyMs: null,
  });

  const clearPending = useCallback(() => {
    if (pendingRef.current?.timer) clearTimeout(pendingRef.current.timer);
    pendingRef.current = null;
  }, []);

  const abandonPending = useCallback(() => {
    if (!pendingRef.current) return;
    clearPending();
    statsRef.current.abandon += 1;
    voiceRef.current?.abandon();
  }, [clearPending]);

  /** Whether another speculative connect is allowed right now. */
  const mayPreconnect = useCallback(() => {
    const now = Date.now();
    const recent = recentAttemptsRef.current.filter((t) => now - t < 60_000);
    recentAttemptsRef.current = recent;
    if (recent.length >= MAX_ATTEMPTS_PER_MINUTE) return false;
    if (recent.length && now - recent[recent.length - 1] < MIN_ATTEMPT_GAP_MS) return false;
    return true;
  }, []);

  /**
   * The microphone and audio contexts the detector already has open, for a
   * voice session to borrow.
   *
   * Empty until the engine is ready, in which case the session opens its own —
   * which is what happens on the very first tap, before anything is warm.
   */
  const resources = useCallback(() => {
    const engineHandle = engineRef.current;
    if (!engineHandle?.ready) return {};
    return {
      stream: engineHandle.stream,
      captureCtx: engineHandle.captureCtx,
      playbackCtx: engineHandle.playbackCtx,
      audioSource: engineHandle,
    };
  }, []);

  const onMaybe = useCallback(() => {
    const current = voiceRef.current;
    // Only while nothing is happening. A session already open owns the
    // conversation, and a second one would fight it for the microphone.
    if (!current || current.status !== 'idle' || pendingRef.current) return;
    if (!mayPreconnect()) {
      statsRef.current.throttled += 1;
      return;
    }

    recentAttemptsRef.current.push(Date.now());
    statsRef.current.preconnect += 1;
    current.start({ provisional: true, resources: resources() });
    pendingRef.current = {
      at: Date.now(),
      timer: setTimeout(() => abandonPending(), ABANDON_AFTER_MS),
    };
  }, [mayPreconnect, abandonPending, resources]);

  const onDetect = useCallback(() => {
    const current = voiceRef.current;
    if (!current) return;
    if (current.status !== 'idle' && !pendingRef.current) return;

    // Acknowledge first, before any network work. Whatever the rest of this
    // costs, the person knows they were heard inside 50 ms — which is what
    // makes the remainder tolerable.
    engineRef.current?.sound('wake', getSettings().wakeWord?.sound ?? 'chime');

    // Everything from just before the wake word, so the question asked in the
    // same breath survives the connection delay.
    const recent = engineRef.current?.takeRecent(1.5);

    const wasPending = Boolean(pendingRef.current);
    if (wasPending) {
      statsRef.current.lastLatencyMs = Date.now() - pendingRef.current.at;
      clearPending();
    }
    statsRef.current.confirm += 1;

    // The speculative session is already connected, so this only starts the
    // audio. If there was no pre-connect — the score jumped straight past the
    // threshold, or speculation was throttled — this is the ordinary cold path,
    // still with the microphone and contexts already warm.
    if (!current.commit(recent)) current.start({ resources: resources() });
  }, [clearPending, resources]);

  const onRelease = useCallback(() => abandonPending(), [abandonPending]);

  // ---------------------------------------------------------------------
  // SpeechRecognition fallback
  // ---------------------------------------------------------------------

  const startSpeechFallback = useCallback(() => {
    const SpeechRecognition =
      window.SpeechRecognition || /** @type {any} */ (window).webkitSpeechRecognition;
    if (!SpeechRecognition) return false;

    const wakeWords = ['hey gamira', 'hello gamira', 'hi gamira', 'gamira'];
    let active = true;
    let recognition = null;

    const begin = () => {
      if (!active) return;
      recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = lang;

      recognition.onresult = (event) => {
        // Only what is new. Scanning the whole cumulative transcript meant one
        // "gamira" kept matching on every subsequent result forever.
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const said = event.results[i][0].transcript.toLowerCase();
          if (!wakeWords.some((w) => said.includes(w))) continue;
          // Restart, or the same phrase re-matches on the next event.
          try { recognition.abort(); } catch { /* already stopping */ }
          onDetect();
          return;
        }
      };

      recognition.onend = () => {
        if (active) {
          try { recognition.start(); } catch { /* already starting */ }
        }
      };

      recognition.onerror = (event) => {
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          active = false;
          setError(new Error('Gamira needs permission to use the microphone.'));
        }
      };

      try { recognition.start(); } catch { /* already started */ }
    };

    begin();
    recognitionRef.current = {
      stop() {
        active = false;
        if (!recognition) return;
        recognition.onend = null;
        try { recognition.stop(); } catch { /* ignore */ }
      },
    };
    return true;
  }, [onDetect, lang]);

  // ---------------------------------------------------------------------
  // Arming
  // ---------------------------------------------------------------------

  const disarm = useCallback(() => {
    clearPending();
    engineRef.current?.stop();
    engineRef.current = null;
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setArmed(false);
    setEngine('off');
    setTelemetry(null);
  }, [clearPending]);

  /**
   * Start listening. **Must be called from a user gesture**: opening the
   * microphone, resuming both AudioContexts and unlocking audio playback for
   * the chime all require one.
   */
  const arm = useCallback(() => {
    if (engineRef.current || recognitionRef.current || blockedRef.current) return;
    setError(null);

    const settings = getSettings().wakeWord || {};
    const preferred = settings.engine || 'auto';

    if (preferred === 'speech') {
      const started = startSpeechFallback();
      blockedRef.current = !started;
      setArmed(started);
      setEngine(started ? 'speech' : 'off');
      return;
    }

    setArmed(true);
    engineRef.current = startWakeWordEngine({
      thresholdOffset: settings.sensitivityOffset || 0,
      // Above 1.0 the smoothed score can never reach it, which is how
      // speculation is turned off without a second code path.
      preconnectThreshold:
        settings.preconnect === false ? 2 : (settings.preconnectThreshold ?? 0.4),
      onReady: (info) => {
        setEngine('onnx');
        if (wantTelemetry) setTelemetry((t) => ({ ...t, ...info }));
      },
      onScore: wantTelemetry
        ? (score) => setTelemetry((t) => ({ ...t, ...score, ...statsRef.current }))
        : undefined,
      onMaybe,
      onDetect,
      onRelease,
      onError: (err) => {
        // The trained detector could not start — no bundle, no WASM, no
        // microphone. Fall back rather than leaving the app with no hands-free
        // path at all, but say so: silently degrading to something that ships
        // every word in the room to a third party is not a quiet failure.
        // eslint-disable-next-line no-console
        console.warn('Gamira wake word: falling back to SpeechRecognition —', err.message);
        engineRef.current = null;
        if (preferred === 'onnx' || !startSpeechFallback()) {
          // Nothing left to try. Latched so the automatic arm does not ask for
          // the microphone again on every tap.
          blockedRef.current = true;
          setError(err);
          setArmed(false);
          setEngine('off');
          return;
        }
        setEngine('speech');
      },
    });
  }, [startSpeechFallback, onMaybe, onDetect, onRelease, wantTelemetry]);

  const toggle = useCallback(() => {
    if (armed) disarm();
    else arm();
  }, [armed, arm, disarm]);

  /**
   * Start listening on the first touch anywhere in the app.
   *
   * Opening the microphone, resuming both AudioContexts and unlocking audio
   * playback for the chime all require a user gesture, so *some* interaction
   * has to come first — but it must not be the microphone button. That button
   * also starts a conversation, and a live conversation pauses the detector, so
   * tying arming to it meant the wake word only ever began working after
   * somebody had started and then ended a call by hand. Which is to say: it
   * never appeared to work at all.
   *
   * Any tap will do, and people tap. Capture phase so it fires even where a
   * handler stops propagation.
   */
  useEffect(() => {
    if (!enabled || armed || blockedRef.current) return;
    const options = { once: true, capture: true };
    const onGesture = () => arm();
    window.addEventListener('pointerdown', onGesture, options);
    window.addEventListener('keydown', onGesture, options);
    return () => {
      window.removeEventListener('pointerdown', onGesture, options);
      window.removeEventListener('keydown', onGesture, options);
    };
  }, [enabled, armed, arm]);

  // While a conversation is live the detector stops scoring — Gamira's own
  // replies are in the room, and it should not wake itself. Everything stays
  // warm, so resuming afterwards costs nothing.
  const voiceStatus = voice?.status;
  const voiceProvisional = voice?.provisional;
  useEffect(() => {
    const active = voiceStatus !== 'idle' && voiceStatus !== 'error' && !voiceProvisional;
    if (active) engineRef.current?.pause();
    else engineRef.current?.resume();
  }, [voiceStatus, voiceProvisional]);

  // Never leave the microphone open behind a navigation.
  useEffect(() => () => {
    engineRef.current?.stop();
    recognitionRef.current?.stop();
  }, []);

  return {
    /** 'onnx' | 'speech' | 'off' */
    engine,
    armed,
    /** Listening for its name right now, as opposed to merely started. */
    listening: armed && engine !== 'off',
    enabled,
    error,
    /** Live scores and counters, for the ?wake=debug overlay. */
    telemetry,
    arm,
    disarm,
    toggle,
    /** Warm microphone and audio contexts for a session started by hand. */
    resources,
    /**
     * Make one of Gamira's sounds through the engine's live playback context.
     * Used for the end-of-conversation sound, which belongs to the session
     * rather than to the detector but shares the same speaker.
     */
    sound: useCallback((event, voice) => engineRef.current?.sound(event, voice), []),
  };
}
