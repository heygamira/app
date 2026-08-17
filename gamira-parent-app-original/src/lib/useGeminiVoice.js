import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ai as aiApi } from '@/api/gamiraClient';
import { startVoiceSession } from '@/lib/geminiVoice';
import { createUiDispatcher } from '@/lib/voiceTools';

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
 * @param {(contactId: string) => {name?: string, phone?: string} | null} [handlers.onDialContact]
 * @param {(doseEventId: string) => void} [handlers.onOpenDose]
 * @param {(reminderId: string) => void} [handlers.onOpenReminder]
 * @param {(outcome?: object) => void} [handlers.onMutation]  something was recorded; reload
 */
export function useGeminiVoice(handlers = {}) {
  const navigate = useNavigate();
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState(null);
  const [transcript, setTranscript] = useState('');
  // The one action waiting on this person: { decisionId, prompt, toolName }.
  const [confirmation, setConfirmation] = useState(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const sessionRef = useRef(null);
  // True while the open session is only a guess: the wake-word detector thought
  // it heard something and started connecting, but has not confirmed it. Such a
  // session must be completely invisible — no status change, no error if it
  // fails, no microphone light in the UI — because most of them come to
  // nothing and the person never said a word.
  const provisionalRef = useRef(false);
  // Transcript chunks stream in mid-sentence, so they are appended — but each
  // turn has to start a fresh line or replies run together into one blob.
  const freshTurnRef = useRef(true);
  // Handlers change on every render of the page that owns them; the session is
  // built once, so it reads them through a ref.
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const stop = useCallback(() => {
    const sessionId = sessionRef.current?.sessionId;
    sessionRef.current?.stop();
    sessionRef.current = null;
    provisionalRef.current = false;
    setStatus('idle');
    setError(null);
    setConfirmation(null);
    // Free the backend session's slot rather than waiting for it to expire.
    if (sessionId) aiApi.closeLiveSession(sessionId).catch(() => {});
  }, []);

  /**
   * Drop a speculative session that came to nothing.
   *
   * Silent by design: the person did not say anything, so there is nothing to
   * tell them about. Only the backend slot needs releasing.
   */
  const abandon = useCallback(() => {
    if (!provisionalRef.current) return;
    const sessionId = sessionRef.current?.sessionId;
    sessionRef.current?.stop();
    sessionRef.current = null;
    provisionalRef.current = false;
    if (sessionId) aiApi.closeLiveSession(sessionId).catch(() => {});
  }, []);

  const dispatchClientTool = useMemo(
    () =>
      createUiDispatcher({
        navigate,
        openDose: (id) => handlersRef.current.onOpenDose?.(id),
        openReminder: (id) => handlersRef.current.onOpenReminder?.(id),
        openSos: () => handlersRef.current.onOpenSos?.(),
        openDialer: (contactId) => handlersRef.current.onDialContact?.(contactId),
      }),
    [navigate]
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
    const { provisional = false, resources = {} } = options;

    provisionalRef.current = provisional;
    if (!provisional) {
      setError(null);
      setTranscript('');
      setConfirmation(null);
      freshTurnRef.current = true;
    }

    sessionRef.current = startVoiceSession({
      createSession: (opts) => aiApi.createLiveSession(opts),
      sendToolCalls: (sessionId, calls) => aiApi.sendToolCalls(sessionId, calls),
      dispatchClientTool,
      provisional,
      autoStream: !provisional,
      stream: resources.stream || null,
      captureCtx: resources.captureCtx || null,
      playbackCtx: resources.playbackCtx || null,
      audioSource: resources.audioSource || null,
      onConfirmationRequired: (request) => setConfirmation(request),
      onStatus: (next) => {
        if (next === 'closed') {
          const wasProvisional = provisionalRef.current;
          sessionRef.current = null;
          provisionalRef.current = false;
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
        setStatus(next);
      },
      onTranscript: (text) => {
        if (freshTurnRef.current) {
          freshTurnRef.current = false;
          setTranscript(text.trimStart());
          return;
        }
        setTranscript((prev) => (prev + text).slice(-400));
      },
      onTurnEnd: () => { freshTurnRef.current = true; },
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
  }, [dispatchClientTool]);

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
    setError(null);
    setTranscript('');
    setConfirmation(null);
    freshTurnRef.current = true;
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

  // Never leave the microphone open behind a navigation.
  useEffect(() => () => sessionRef.current?.stop(), []);

  return {
    status,
    error,
    transcript,
    confirmation,
    confirmBusy,
    acceptConfirmation,
    rejectConfirmation,
    active: status === 'listening' || status === 'speaking' || status === 'working',
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
