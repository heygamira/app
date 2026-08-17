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
    setStatus('idle');
    setError(null);
    setConfirmation(null);
    // Free the backend session's slot rather than waiting for it to expire.
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

  const start = useCallback(() => {
    if (sessionRef.current) return;
    setError(null);
    setTranscript('');
    setConfirmation(null);
    freshTurnRef.current = true;

    sessionRef.current = startVoiceSession({
      createSession: () => aiApi.createLiveSession(),
      sendToolCalls: (sessionId, calls) => aiApi.sendToolCalls(sessionId, calls),
      dispatchClientTool,
      onConfirmationRequired: (request) => setConfirmation(request),
      onStatus: (next) => {
        if (next === 'closed') {
          sessionRef.current = null;
          setConfirmation(null);
          // A failure reports onError first and then closes; don't let the
          // close wipe the error state the user still needs to see.
          setStatus((prev) => (prev === 'error' ? prev : 'idle'));
          return;
        }
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
        sessionRef.current = null;
        setConfirmation(null);
        setError(err);
        setStatus('error');
      },
    });
  }, [dispatchClientTool]);

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
  };
}
