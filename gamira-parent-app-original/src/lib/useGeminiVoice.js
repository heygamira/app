import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ai as aiApi } from '@/api/gamiraClient';
import { startVoiceSession } from '@/lib/geminiVoice';
import { getSettings } from '@/lib/userSettings';
import { createUiDispatcher, isBackendMutation } from '@/lib/voiceTools';

/**
 * React wrapper around the Gemini Live voice session.
 *
 * status: 'idle' | 'connecting' | 'listening' | 'speaking' | 'working' | 'error'
 *
 * The session comes from the backend through the normal authenticated API
 * client — no direct fetch, no token server, no key in this app. The backend
 * decides which person the session is about and which tools it may use.
 *
 * @param {object} [handlers] optional client-tool hooks the page provides
 * @param {() => void} [handlers.onOpenSos]     open the real SOS confirmation
 * @param {() => boolean} [handlers.onCancelSosCountdown]  stop a running SOS
 *   countdown; returns whether one was actually running
 * @param {(contactId: string) => {name?: string, phone?: string} | null} [handlers.onDialContact]
 * @param {(doseEventId: string) => void} [handlers.onOpenDose]
 * @param {(reminderId: string) => void} [handlers.onOpenReminder]
 * @param {(outcome?: object) => void} [handlers.onMutation]  something was recorded; reload
 * @param {(result: {name: string, response: object}) => void} [handlers.onToolResult]
 *   a backend tool finished, named, so a screen can react to what was done
 * @param {(reason: 'idle' | 'goodbye') => void} [handlers.onAutoStop]  the session closed itself
 * @param {object} [options]
 * @param {string} [options.timezone] the cared-for person's timezone, for the
 *   clock tool — the device's own is the fallback, and a phone that travels
 *   would otherwise answer "what time is it" about the wrong place.
 */
export function useGeminiVoice(handlers = {}, { timezone = null } = {}) {
  const navigate = useNavigate();
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState(null);
  const [transcript, setTranscript] = useState('');
  // Both sides of what is being said, newest last. The person's own words were
  // transcribed all along and handed to nobody, so the screen showed half a
  // conversation — which to somebody unsure whether they were heard reads
  // exactly like not being heard.
  const [turns, setTurns] = useState([]);
  // The one action waiting on this person: { decisionId, prompt, toolName }.
  const [confirmation, setConfirmation] = useState(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const sessionRef = useRef(null);
  // When the model last did anything at all. Drives the idle auto-stop below.
  const lastActivityRef = useRef(0);
  const touch = () => { lastActivityRef.current = Date.now(); };
  // The idle timer reads this: a dialog waiting on a person is not idleness.
  const confirmationRef = useRef(null);
  confirmationRef.current = confirmation;
  // True while the open session is only a guess: the wake-word detector thought
  // it heard something and started connecting, but has not confirmed it. Such a
  // session must be completely invisible — no status change, no error if it
  // fails, no microphone light in the UI — because most of them come to
  // nothing and the person never said a word.
  const provisionalRef = useRef(false);
  // Transcript chunks stream in mid-sentence, so they are appended — but each
  // turn has to start a fresh line or replies run together into one blob.
  const freshTurnRef = useRef(true);
  // True only while she is actually speaking. The microphone stays hot the
  // whole time she talks, so it can be barge-in the instant she needs to be
  // interrupted — but that means it also picks up an echo of her own voice,
  // or a stray "mm-hmm", none of which is a real interruption. A genuine
  // barge-in ends her turn and moves status off 'speaking' before its
  // transcript arrives; a live interim transcript that arrives while this is
  // still true is exactly that background noise, not something they said.
  const speakingRef = useRef(false);
  // Handlers change on every render of the page that owns them; the session is
  // built once, so it reads them through a ref.
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  // How long this session may sit silent before closing itself. Null means the
  // person's own setting, which is what a session they started gets.
  const listenSecondsRef = useRef(null);

  // The person's utterance is finished, so the next thing they say is a new
  // line rather than more of this one. See `appendTurn`.
  const themTurnDoneRef = useRef(false);
  // A goodbye is being finished. The "stopped" chime waits for the socket to
  // close rather than playing over the sentence it is about.
  const goodbyeRef = useRef(false);

  /**
   * Add a chunk to the running transcript.
   *
   * Chunks arrive mid-word, so consecutive ones from the same speaker are
   * joined rather than listed. Capped, because this is what is being said now,
   * not a record of the conversation: that lives in the backend, and putting an
   * unbounded list on an older person's phone would eventually cost them the
   * screen.
   *
   * `replace` is what the person's own transcript needs, and it needs it for
   * **both** of the messages that carry it. The interim transcription is a
   * running best guess at the whole utterance, re-sent as it improves; the
   * finalised one that follows is that same utterance, corrected. Appending
   * either of them repeats the words — the interim once per revision, and the
   * final one whole sentence at a time, which is why their line read like
   * "I have a headacheI have a headache".
   *
   * `endsTurn` is how the two are told apart without a timer: the finalised
   * transcript closes the utterance, so the next interim starts a fresh line
   * instead of overwriting what they just said.
   */
  const appendTurn = useCallback((role, text, { replace = false, endsTurn = false } = {}) => {
    if (!text) return;
    const startFresh = role === 'them' && themTurnDoneRef.current;
    if (role === 'them') themTurnDoneRef.current = endsTurn;
    setTurns((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === role && !startFresh) {
        const merged = {
          ...last,
          // Generous, and the caption line depends on it being generous: that
          // component tracks how much of a turn it has already shown as an
          // offset into this string, and dropping characters off the front
          // moves every offset. 4000 characters is several minutes of speech
          // against a turn she is told to keep to a sentence or two, so the
          // cap is a backstop against a stuck stream rather than something
          // that happens in a conversation.
          text: (replace ? text : last.text + text).slice(-4000),
        };
        return [...prev.slice(0, -1), merged];
      }
      return [...prev, { role, text: text.trimStart(), at: Date.now() }].slice(-12);
    });
  }, []);

  const stop = useCallback(() => {
    // The handle frees the backend's slot itself, on every path out — including
    // the ones this function never sees, like the far end hanging up.
    sessionRef.current?.stop();
    sessionRef.current = null;
    provisionalRef.current = false;
    listenSecondsRef.current = null;
    setStatus('idle');
    setError(null);
    setConfirmation(null);
  }, []);

  /**
   * Drop a speculative session that came to nothing.
   *
   * Silent by design: the person did not say anything, so there is nothing to
   * tell them about. Only the backend slot needs releasing.
   */
  const abandon = useCallback(() => {
    if (!provisionalRef.current) return;
    sessionRef.current?.stop();
    sessionRef.current = null;
    provisionalRef.current = false;
  }, []);

  const dispatchClientTool = useMemo(
    () =>
      createUiDispatcher({
        navigate,
        timezone,
        openDose: (id) => handlersRef.current.onOpenDose?.(id),
        openReminder: (id) => handlersRef.current.onOpenReminder?.(id),
        openSos: () => handlersRef.current.onOpenSos?.(),
        cancelSosCountdown: () => handlersRef.current.onCancelSosCountdown?.(),
        openDialer: (contactId) => handlersRef.current.onDialContact?.(contactId),
        // "Bye" ends the conversation — but only once she has finished saying
        // goodbye. She calls this tool in the same turn as "talk to you
        // later", and the audio for that sentence is already scheduled, so
        // stopping here cut her off mid-word. `finish()` stops listening
        // immediately and closes when the sentence has actually been said.
        endConversation: () => {
          const session = sessionRef.current;
          if (!session) return;
          // The handle is deliberately kept until the socket actually closes.
          // It is what stops a wake word opening a second session over the top
          // of the goodbye, and what a stop button would still act on.
          goodbyeRef.current = true;
          session.finish();
        },
      }),
    [navigate, timezone, stop]
  );

  /**
   * Open a session.
   *
   * @param {object} [options]
   * @param {boolean} [options.provisional] connect speculatively and stay silent
   *   until `commit` — the wake word's pre-connect path.
   * @param {object} [options.resources] microphone and audio contexts the
   *   wake-word engine already has open, so none of that is on the critical
   *   path: `{ stream, captureCtx, playbackCtx, audioSource }`.
   */
  const start = useCallback((options = {}) => {
    if (sessionRef.current) return;
    const {
      provisional = false,
      resources = {},
      openingBrief = null,
      listenSeconds = null,
    } = options;

    provisionalRef.current = provisional;
    // A session Gamira opened herself closes sooner than one somebody started
    // by pressing a button. Nobody asked for it, so an unanswered one should
    // not sit there holding a microphone for the ordinary minute.
    listenSecondsRef.current = listenSeconds;
    touch();
    if (!provisional) {
      setError(null);
      setTranscript('');
      setTurns([]);
      setConfirmation(null);
      freshTurnRef.current = true;
      themTurnDoneRef.current = false;
    }

    sessionRef.current = startVoiceSession({
      createSession: (opts) => aiApi.createLiveSession(opts),
      closeSession: (sessionId) => aiApi.closeLiveSession(sessionId).catch(() => {}),
      // Losing a transcript is a shame; interrupting the conversation that
      // produced it would be worse.
      storeTranscript: (sessionId, turns, options) =>
        aiApi.storeTranscript(sessionId, turns, options).catch(() => {}),
      sendToolCalls: (sessionId, calls) => aiApi.sendToolCalls(sessionId, calls),
      dispatchClientTool,
      provisional,
      openingBrief,
      // A speculative session sends nothing until the wake word is confirmed;
      // a proactive one sends nothing until Gamira has finished her sentence.
      autoStream: !provisional && !openingBrief,
      stream: resources.stream || null,
      captureCtx: resources.captureCtx || null,
      playbackCtx: resources.playbackCtx || null,
      audioSource: resources.audioSource || null,
      onConfirmationRequired: (request) => {
        touch();
        setConfirmation(request);
      },
      // Answered out loud. The backend has already run it — or not — so all
      // that is left here is to take the dialog away and reload what changed.
      onConfirmationResolved: ({ decisionId, response }) => {
        touch();
        setConfirmation((prev) => (prev?.decisionId === decisionId ? null : prev));
        if (response?.status === 'ok' && response?.outcome !== 'cancelled') {
          handlersRef.current.onMutation?.({ tool_response: response });
        }
      },
      onStatus: (next) => {
        speakingRef.current = next === 'speaking';
        if (next === 'closed') {
          const wasProvisional = provisionalRef.current;
          const wasGoodbye = goodbyeRef.current;
          goodbyeRef.current = false;
          sessionRef.current = null;
          provisionalRef.current = false;
          if (wasGoodbye) handlersRef.current.onAutoStop?.('goodbye');
          if (wasProvisional) return; // a guess ending is not an event
          setConfirmation(null);
          // A failure reports onError first and then closes; don't let the
          // close wipe the error state the user still needs to see.
          setStatus((prev) => (prev === 'error' ? prev : 'idle'));
          return;
        }
        // Nothing about an unconfirmed guess reaches the screen. Showing
        // "connecting…" every time the detector half-heard something would be
        // worse than the latency it exists to hide.
        if (provisionalRef.current) return;
        // Every status move is the model doing something — audio arriving, a
        // turn ending, a tool resolving. That is what "not idle" means.
        touch();
        setStatus(next);
      },
      onToolResult: (result) => {
        touch();
        handlersRef.current.onToolResult?.(result);
        if (result?.response?.status === 'ok' && isBackendMutation(result.name)) {
          handlersRef.current.onMutation?.({ tool_response: result.response });
        }
      },
      onTranscript: (text) => {
        touch();
        appendTurn('gamira', text);
        if (freshTurnRef.current) {
          freshTurnRef.current = false;
          setTranscript(text.trimStart());
          return;
        }
        setTranscript((prev) => (prev + text).slice(-400));
      },
      onUserTranscript: (text, meta) => {
        // A live interim transcript while she is still speaking is the open
        // mic hearing itself, not them talking — showing it would hijack her
        // caption over nothing (see `speakingRef` above). A genuine barge-in
        // has already moved status off 'speaking' by the time its transcript
        // lands, so this only ever drops noise, never a real interruption.
        // The finalised transcript is always real, whenever it lands, so it
        // is never dropped.
        if (meta?.live && speakingRef.current) return;
        touch();
        // Both forms replace; only the finalised one closes the utterance.
        appendTurn('them', text, { replace: true, endsTurn: !meta?.live });
      },
      onTurnEnd: () => {
        touch();
        freshTurnRef.current = true;
      },
      onError: (err) => {
        const wasProvisional = provisionalRef.current;
        sessionRef.current = null;
        provisionalRef.current = false;
        if (wasProvisional) {
          // Nobody asked for this session, so nobody needs to hear that it
          // failed. The next wake word takes the ordinary cold path.
          // eslint-disable-next-line no-console
          console.warn('Gamira voice: a speculative session failed', err);
          return;
        }
        setConfirmation(null);
        setError(err);
        setStatus('error');
      },
    });
  }, [dispatchClientTool, appendTurn]);

  /**
   * The wake word was confirmed: turn the speculative session into a real one.
   *
   * Audio starts flowing immediately and the backend is told afterwards. That
   * ordering is the entire point — waiting for the promote round trip would put
   * back a chunk of the delay this was built to remove. The session is already
   * authorised and already connected; promoting is bookkeeping, not permission.
   *
   * @param {Int16Array} [prependAudio] the ring buffer's last moments, so the
   *   wake word and anything said with it are not lost.
   */
  const commit = useCallback((prependAudio) => {
    const session = sessionRef.current;
    if (!session || !provisionalRef.current) return false;

    provisionalRef.current = false;
    touch();
    setError(null);
    setTranscript('');
    setTurns([]);
    setConfirmation(null);
    freshTurnRef.current = true;
    themTurnDoneRef.current = false;
    setStatus('connecting');

    if (prependAudio?.length) session.prependAudio(prependAudio);
    session.beginStreaming();

    const sessionId = session.sessionId;
    if (sessionId) {
      aiApi.promoteLiveSession(sessionId).catch((err) => {
        // The backend refused to charge for this session — over the hourly
        // limit, or it expired before anyone spoke. It will stop honouring tool
        // calls, so end it now rather than let it half-work.
        if (sessionRef.current !== session) return;
        sessionRef.current = null;
        session.stop();
        setError(err);
        setStatus('error');
      });
    }
    return true;
  }, []);

  const toggle = useCallback(() => {
    if (sessionRef.current) stop();
    else start();
  }, [start, stop]);

  /**
   * The person said yes. Run it, then tell the model what actually happened.
   *
   * The result sent to Gemini is the backend's persisted outcome, so the
   * assistant can only say a dose was recorded once a dose really was.
   */
  const acceptConfirmation = useCallback(async () => {
    const pending = confirmation;
    if (!pending || confirmBusy) return;
    setConfirmBusy(true);
    try {
      const outcome = await aiApi.confirmAction(pending.decisionId);
      sessionRef.current?.resolveConfirmation(
        pending.decisionId,
        outcome.tool_response || { status: 'ok' }
      );
      if (outcome?.tool_response?.status === 'ok') {
        handlersRef.current.onMutation?.(outcome);
      }
    } catch (err) {
      sessionRef.current?.resolveConfirmation(pending.decisionId, {
        status: 'error',
        error: 'action_failed',
        message: 'That did not work. Nothing changed.',
      });
      setError(err);
    } finally {
      setConfirmBusy(false);
      setConfirmation(null);
    }
  }, [confirmation, confirmBusy]);

  /** The person said no. Nothing is written but the refusal itself. */
  const rejectConfirmation = useCallback(async () => {
    const pending = confirmation;
    if (!pending || confirmBusy) return;
    setConfirmBusy(true);
    try {
      const outcome = await aiApi.rejectAction(pending.decisionId);
      sessionRef.current?.resolveConfirmation(
        pending.decisionId,
        outcome.tool_response || {
          status: 'error',
          error: 'rejected_by_user',
          message: 'They said no, so nothing was changed.',
        }
      );
    } catch {
      sessionRef.current?.resolveConfirmation(pending.decisionId, {
        status: 'error',
        error: 'rejected_by_user',
        message: 'They said no, so nothing was changed.',
      });
    } finally {
      setConfirmBusy(false);
      setConfirmation(null);
    }
  }, [confirmation, confirmBusy]);

  /**
   * Close a conversation nobody is having.
   *
   * An open session streams the microphone to Gemini continuously — it is
   * billed for every second it is up, it holds one of two concurrent slots for
   * half an hour, and it keeps the microphone live in the room. None of that
   * should depend on somebody remembering to press stop, and in this app they
   * often will not: the phone gets put down mid-sentence, or the person walks
   * away, or the answer was all they wanted.
   *
   * "Idle" means the model has said and done nothing for the timeout — no
   * audio, no transcript, no completed turn, no tool call. While somebody is
   * actually talking, Gemini is replying, so the clock keeps resetting.
   */
  const active = status === 'listening' || status === 'speaking' || status === 'working';

  useEffect(() => {
    const seconds =
      listenSecondsRef.current ?? (getSettings().voiceSession?.autoStopSeconds ?? 60);
    // 0 means never, for anyone who would rather it stayed open.
    if (!seconds || !active) return undefined;

    const timer = setInterval(() => {
      if (Date.now() - lastActivityRef.current < seconds * 1000) return;
      // A confirmation on screen is somebody deciding, not somebody absent.
      if (confirmationRef.current) return;
      stop();
      handlersRef.current.onAutoStop?.('idle');
    }, 2000);
    return () => clearInterval(timer);
  }, [active, stop]);

  // Never leave the microphone open behind a navigation.
  useEffect(() => () => sessionRef.current?.stop(), []);

  /**
   * Say something into a conversation that is already happening.
   *
   * Returns false when there is nothing open, which is how the caller knows to
   * start a session instead. Two sessions at once would fight over one
   * microphone; talking over somebody mid-sentence to mention a late tablet
   * would be worse than the late tablet.
   */
  const briefInto = useCallback((text) => {
    const session = sessionRef.current;
    if (!session || provisionalRef.current || !text) return false;
    session.brief(text);
    touch();
    return true;
  }, []);

  return {
    status,
    error,
    transcript,
    turns,
    briefInto,
    confirmation,
    confirmBusy,
    acceptConfirmation,
    rejectConfirmation,
    active,
    connecting: status === 'connecting',
    working: status === 'working',
    start,
    stop,
    toggle,
    // The wake word's three-step path: connect on a maybe, keep or drop it once
    // the detector is sure.
    commit,
    abandon,
    get provisional() { return provisionalRef.current; },
  };
}
