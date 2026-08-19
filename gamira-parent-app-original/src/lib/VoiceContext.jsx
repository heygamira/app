import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useGeminiVoice } from '@/lib/useGeminiVoice';
import { useWakeWord } from '@/lib/useWakeWord';
import { useProactive } from '@/lib/useProactive';
import { useWatchRelay } from '@/lib/useWatchRelay';
import { useSeniorCare } from '@/lib/useSeniorCare';
import { langCode, useI18n } from '@/lib/i18n';
import { wellbeingChecks as checksApi } from '@/api/gamiraClient';
import VoiceConfirmDialog from '@/components/gamira/VoiceConfirmDialog';

/**
 * Gamira's voice, for the whole app rather than for one screen.
 *
 * This used to live inside `pages/Home.jsx`. Everything worked there and
 * nowhere else: navigating to Health or Settings unmounted the hooks, which
 * tore down the microphone, the wake-word detector and any conversation in
 * progress. An app meant to be run by voice had voice on one screen out of six,
 * and the person most likely to need it hands-free was the person most likely
 * to have wandered off the home screen.
 *
 * So it is a layout route that wraps every signed-in page. One session, one
 * detector, one confirmation dialog, surviving navigation — which also means
 * Gamira can *open* a conversation whatever screen somebody is looking at.
 *
 * What it deliberately does not own: the SOS dialog and the schedule cards.
 * Those belong to the screens that draw them; this publishes the handlers they
 * register, so a tool call can reach them without this file knowing anything
 * about how they look.
 */

const VoiceContext = createContext(null);

// How long the microphone stays open after Gamira has spoken first. Long
// enough to answer a question, short enough that a phone left on a table is
// not streaming a room to anybody.
const PROACTIVE_LISTEN_SECONDS = 20;
// How often to look for a question a watch flag has left owed.
const CHECK_POLL_MS = 30_000;
// How often to re-read doses and reminders. Without this, a dose or reminder
// created after this screen loaded — including the ordinary ones a backend
// sweep creates through the day — never appears here until something else
// happens to reload the page, so a schedule item could come and go due without
// this device ever finding out. Wellbeing checks already poll on their own
// timer above; this is the same idea for the data a proactive nudge is judged
// against.
const CARE_POLL_MS = 5_000;

export function useVoice() {
  const value = useContext(VoiceContext);
  if (!value) {
    throw new Error('useVoice must be used inside VoiceProvider.');
  }
  return value;
}

export default function VoiceProvider() {
  const { lang } = useI18n();
  const { self, seniorId, doses, reminders, contacts, loading, error, reload } =
    useSeniorCare({ doses: true, reminders: true, contacts: true, refreshMs: CARE_POLL_MS });

  // This senior's paired watch, if any, reaches the server only through this
  // app — never on its own. See useWatchRelay for why.
  //
  // `onMutation` has to be a stable reference. An inline arrow here is a new
  // function every render, and `useSeniorCare`'s own 5-second poll re-renders
  // this provider that often — so the hook's 30-second reading-flush timer
  // never survived that long: its effect kept tearing down and restarting on
  // every render, always mid-count. Readings piled up in the relay's mailbox,
  // ingested but never actually flushed to the backend.
  const onWatchRelayMutation = useCallback(() => reload({ quiet: true }), [reload]);
  useWatchRelay({
    seniorId,
    person: self?.preferred_name,
    onMutation: onWatchRelayMutation,
  });

  // Screens register what they can do; nothing is built from what a model says.
  /** @type {import('react').MutableRefObject<Record<string, Function>>} */
  const screenRef = useRef({});
  const register = useCallback((handlers) => {
    Object.assign(screenRef.current, handlers);
    return () => {
      for (const key of Object.keys(handlers)) delete screenRef.current[key];
    };
  }, []);

  const contactsRef = useRef(contacts);
  contactsRef.current = contacts;
  const wakeSoundRef = useRef(null);

  // A question a watch flag left owed, and the one currently being asked.
  const [pendingCheck, setPendingCheck] = useState(null);
  const askedCheckRef = useRef(null);

  const dialContact = useCallback((contactId) => {
    const contact = contactsRef.current.find((c) => c.id === contactId);
    if (!contact) return null;
    window.location.href = `tel:${contact.phone}`;
    return { name: contact.name, phone: contact.phone };
  }, []);

  const voice = useGeminiVoice(
    {
      onOpenSos: () => screenRef.current.openSos?.(),
      onCancelSosCountdown: () => Boolean(screenRef.current.cancelSosCountdown?.()),
      onDialContact: dialContact,
      onOpenDose: (id) => screenRef.current.openDose?.(id),
      onOpenReminder: (id) => screenRef.current.openReminder?.(id),
      onMutation: () => reload({ quiet: true }),
      // Something was done by voice, named. The screens do not poll for this:
      // an alert withdrawn out loud has to close the dialog that says it was
      // sent, and it has to happen now, not at the next refresh.
      onToolResult: ({ name, response }) => {
        if (response?.status !== 'ok') return;
        if (name === 'cancel_my_sos') screenRef.current.sosWithdrawn?.();
        if (name === 'answer_wellbeing_check') setPendingCheck(null);
      },
      onAutoStop: () => wakeSoundRef.current?.('stopped'),
    },
    { timezone: self?.timezone || null }
  );

  const wake = useWakeWord(voice, { lang: langCode[lang] || 'en-US' });
  wakeSoundRef.current = wake.sound;

  const { start: startVoice, stop: stopVoice, status, active } = voice;
  const { warmResources } = wake;

  /**
   * Start talking, sharing the detector's microphone rather than opening a
   * second one. Every path into a conversation goes through here — the button,
   * the nudge card, a proactive brief — so none of them can quietly take the
   * cold path the way the nudge card used to.
   */
  const talk = useCallback(
    async (options = {}) => {
      const resources = await warmResources();
      startVoice({ ...options, resources });
    },
    [startVoice, warmResources]
  );

  const statusRef = useRef(voice.status);
  statusRef.current = voice.status;

  /**
   * Gamira says one thing, then listens briefly.
   *
   * If a conversation is already open, the brief joins it instead of opening a
   * second session — talking over somebody mid-sentence to tell them their
   * tablet is late would be worse than the late tablet.
   */
  const speakFirst = useCallback(
    async (brief) => {
      if (!brief) return false;
      if (voice.briefInto(brief)) return true;
      try {
        await talk({ openingBrief: brief, listenSeconds: PROACTIVE_LISTEN_SECONDS });
      } catch (error) {
        // Worth a line in the console rather than a silent nothing: this used
        // to be an unhandled rejection inside an effect, so a microphone
        // refusal looked exactly like a companion with nothing to say.
        // eslint-disable-next-line no-console
        console.warn('Gamira could not start speaking:', error);
        return false;
      }
      // `startVoice` returns before the socket is up, so a session that fails
      // to connect reports through `onError` a moment later. Leaving idle is
      // the observable part of having started.
      return statusRef.current !== 'error';
    },
    [talk, voice]
  );

  const toggle = useCallback(() => {
    if (active || status === 'connecting') {
      stopVoice();
      return;
    }
    talk();
  }, [active, status, stopVoice, talk]);

  // ------------------------------------------------------------------ //
  // Speaking first
  // ------------------------------------------------------------------ //

  const { nudge, dismiss: dismissNudge, spoken } = useProactive({
    doses,
    reminders,
    timezone: self?.timezone || null,
    ready: !loading && Boolean(seniorId),
  });

  const spokenNudgeRef = useRef(null);
  // The conversation a nudge opened: which nudge it was, and whether it ever
  // actually got going. Both are needed to know when the card has done its job.
  const nudgeTalkRef = useRef({ key: null, opened: false });
  useEffect(() => {
    if (!nudge || spokenNudgeRef.current === nudge.key) return;
    spokenNudgeRef.current = nudge.key;
    let cancelled = false;
    (async () => {
      nudgeTalkRef.current = { key: nudge.key, opened: false };
      const said = await speakFirst(nudge.brief);
      if (cancelled) return;
      if (said) {
        // Only now is it "already said today". Marking it before speaking meant
        // one failed session burned that dose for the rest of the day.
        spoken(nudge.key);
      } else {
        // Let the next sweep try again rather than losing it silently.
        spokenNudgeRef.current = null;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [nudge, speakFirst, spoken]);

  /**
   * The card goes when the conversation about it is over.
   *
   * "Dismissible by voice" without a dismiss tool: she says the thing, they
   * answer or they do not, the session closes, and the card that existed to
   * repeat her has nothing left to say. Leaving it up meant a spoken reminder
   * ended with something to tap — which is the whole thing this app is trying
   * not to be.
   *
   * `opened` is why this is two lines rather than one. `status` is 'idle' for
   * a moment before the session connects too, and dismissing then would take
   * the card away before she had said anything at all.
   */
  useEffect(() => {
    if (!nudge || nudgeTalkRef.current.key !== nudge.key) return undefined;
    if (active) {
      nudgeTalkRef.current.opened = true;
      return undefined;
    }
    if (!nudgeTalkRef.current.opened || status !== 'idle') return undefined;
    const timer = setTimeout(() => {
      nudgeTalkRef.current = { key: null, opened: false };
      dismissNudge();
    }, 1500);
    return () => clearTimeout(timer);
  }, [nudge, active, status, dismissNudge]);

  // A watch flagged one of their readings, so there is a question owed. The
  // backend tells the family if nobody answers; asking is this app's half.
  useEffect(() => {
    if (!seniorId) return undefined;
    let cancelled = false;
    const look = async () => {
      try {
        const rows = await checksApi.list(seniorId);
        if (!cancelled) setPendingCheck(rows[0] || null);
      } catch {
        // A poll that fails is not worth a message on this screen: the
        // escalation happens on the backend whether or not this app is
        // reachable, which is the whole reason it lives there.
      }
    };
    look();
    const timer = setInterval(look, CHECK_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [seniorId]);

  useEffect(() => {
    if (!pendingCheck || askedCheckRef.current === pendingCheck.id) return;
    askedCheckRef.current = pendingCheck.id;
    // Same rule as a nudge: if she could not be started, let the next poll try
    // again. The backend tells the family either way, so a silent failure here
    // would cost them the chance to answer before it does.
    const ask = speakFirst(
      '[You are starting this conversation, not them. Their watch flagged ' +
        `one of their readings and said: "${pendingCheck.reason}". Ask them ` +
        'once, plainly and calmly, how they are feeling. You may say what ' +
        'their watch reported, as something their watch said — never say ' +
        'whether the number is good or bad, high or low. Then report what ' +
        'they tell you with answer_wellbeing_check. If they do not answer, ' +
        'or you cannot tell what they meant, do not call it at all.]'
    );
    ask.then((said) => {
      if (!said) askedCheckRef.current = null;
    });
  }, [pendingCheck, speakFirst]);

  const answerCheck = useCallback(
    async (alright) => {
      if (!pendingCheck) return;
      try {
        await checksApi.answer(pendingCheck.id, alright);
      } finally {
        setPendingCheck(null);
      }
    },
    [pendingCheck]
  );

  const value = useMemo(
    () => ({
      voice,
      wake,
      status,
      active,
      talk,
      speakFirst,
      toggle,
      stop: stopVoice,
      register,
      nudge,
      dismissNudge,
      pendingCheck,
      answerCheck,
      self,
      seniorId,
      // The day's care data, loaded once here and shared. Gamira needs it to
      // know what is overdue; the screens need it to draw. Two copies would be
      // two sets of requests and, worse, two answers that could disagree.
      doses,
      reminders,
      contacts,
      loading,
      error,
      reload,
    }),
    [
      voice, wake, status, active, talk, speakFirst, toggle, stopVoice, register,
      nudge, dismissNudge, pendingCheck, answerCheck, self, seniorId,
      doses, reminders, contacts, loading, error, reload,
    ]
  );

  return (
    <VoiceContext.Provider value={value}>
      <Outlet />
      {/* Every voice action that changes something passes through here first,
          on whatever screen the person happens to be looking at. */}
      <VoiceConfirmDialog
        open={Boolean(voice.confirmation)}
        prompt={voice.confirmation?.prompt}
        busy={voice.confirmBusy}
        onConfirm={voice.acceptConfirmation}
        onCancel={voice.rejectConfirmation}
      />
    </VoiceContext.Provider>
  );
}
