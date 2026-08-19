import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useGeminiVoice } from '@/lib/useGeminiVoice';
import { useWakeWord } from '@/lib/useWakeWord';
import { useProactive } from '@/lib/useProactive';
import { useWatchRelay } from '@/lib/useWatchRelay';
import { useAuth } from '@/lib/AuthContext';
import { langCode, useI18n } from '@/lib/i18n';
import { seniors as seniorsApi, wellbeingChecks as checksApi } from '@/api/gamiraClient';
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
// A safety net, not the primary refresh path: a foreground FCM push already
// calls reload() (see usePushRegistration), and so does returning to this tab
// (the visibilitychange listener below). This just bounds how stale the
// screen can get if both of those miss — a dose or reminder created
// elsewhere, or a watch flag raised while this device was asleep, still
// appears within a minute rather than only "eventually." It used to be 5
// seconds, polling doses, reminders and contacts separately every tick
// (~36 requests/minute per open app) plus a second 30-second poll for
// wellbeing checks; both are now one request on this one timer.
const SAFETY_POLL_MS = 60_000;

export function useVoice() {
  const value = useContext(VoiceContext);
  if (!value) {
    throw new Error('useVoice must be used inside VoiceProvider.');
  }
  return value;
}

export default function VoiceProvider() {
  const { lang } = useI18n();
  const { self } = useAuth();
  const seniorId = self?.id;

  const [doses, setDoses] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [wellbeingChecks, setWellbeingChecks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // The one request behind doses, reminders, contacts and pending wellbeing
  // checks — see GET /seniors/{id}/summary. A background refresh must not
  // blank the screen the person is reading.
  const reload = useCallback(
    async ({ quiet = false } = {}) => {
      if (!seniorId) {
        setLoading(false);
        return;
      }
      if (!quiet) setLoading(true);
      try {
        const s = await seniorsApi.summary(seniorId);
        setDoses(s.doses);
        setReminders(s.reminders);
        setContacts(s.emergency_contacts);
        setWellbeingChecks(s.wellbeing_checks);
        setError(null);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    },
    [seniorId]
  );

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (!seniorId) return undefined;
    const timer = setInterval(() => reload({ quiet: true }), SAFETY_POLL_MS);
    return () => clearInterval(timer);
  }, [reload, seniorId]);

  // Catches what the 60-second safety poll otherwise would not until its next
  // tick: a phone put down and picked back up, or switched away from and
  // back to. The same reload() a foreground push already calls.
  useEffect(() => {
    if (!seniorId) return undefined;
    const onVisible = () => {
      if (document.visibilityState === 'visible') reload({ quiet: true });
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [reload, seniorId]);

  // This senior's paired watch, if any, reaches the server only through this
  // app — never on its own. See useWatchRelay for why.
  //
  // `onMutation` has to be a stable reference. An inline arrow here is a new
  // function every render, and re-renders are frequent enough (voice status
  // changes, the safety poll above) that the hook's 30-second reading-flush
  // timer would otherwise keep tearing down and restarting, always mid-count.
  // Readings piled up in the relay's mailbox, ingested but never actually
  // flushed to the backend.
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
  // Tracked as its own state (not read straight from wellbeingChecks) so
  // answering one can clear it immediately rather than waiting for the next
  // reload to confirm the list changed server-side.
  const [pendingCheck, setPendingCheck] = useState(null);
  const askedCheckRef = useRef(null);
  useEffect(() => {
    setPendingCheck(wellbeingChecks[0] || null);
  }, [wellbeingChecks]);

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

  // A watch flagged one of their readings, so there is a question owed —
  // sourced from the same summary reload as everything else above now,
  // rather than its own independent 30-second poll.
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
