import { useCallback, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, Bell, Check, Pill, Settings as SettingsIcon } from 'lucide-react';
import { useI18n, langCode } from '@/lib/i18n';
import { useProactive } from '@/lib/useProactive';
import { useGeminiVoice } from '@/lib/useGeminiVoice';
import { useWakeWord } from '@/lib/useWakeWord';
import { mergeSchedule } from '@/lib/schedule';
import { useSeniorCare } from '@/lib/useSeniorCare';
import { doses as dosesApi, sos as sosApi } from '@/api/gamiraClient';
import {
  METRIC_CARDS,
  OPEN_DOSE_STATUSES,
  clockTime,
  describeMinutes,
  groupReadings,
  readCard,
  untilLocalTime,
} from '@/api/parentData';
import GamiraVoiceButton from '@/components/gamira/GamiraVoiceButton';
import GamiraStatusPill from '@/components/gamira/GamiraStatusPill';
import ProactiveNudge from '@/components/gamira/ProactiveNudge';
import GamiraCard from '@/components/gamira/GamiraCard';
import GamiraScheduleCard from '@/components/gamira/GamiraScheduleCard';
import GamiraSectionHeader from '@/components/gamira/GamiraSectionHeader';
import GamiraMetricCard from '@/components/gamira/GamiraMetricCard';
import GamiraSOSButton from '@/components/gamira/GamiraSOSButton';
import VoiceConfirmDialog from '@/components/gamira/VoiceConfirmDialog';
import WakeWordDebug from '@/components/gamira/WakeWordDebug';
import ThemeToggle from '@/components/ThemeToggle';

export default function Home() {
  const { t, lang } = useI18n();
  const navigate = useNavigate();

  const { self, seniorId, doses, reminders, readings, contacts, loading, error, reload } =
    useSeniorCare({ doses: true, reminders: true, readings: true, contacts: true });

  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);
  // Bumped to open the real SOS dialog. The assistant's `prepare_sos` tool ends
  // up here: it opens the screen, and the person still presses the button.
  const [sosSignal, setSosSignal] = useState(0);
  const contactsRef = useRef(contacts);
  contactsRef.current = contacts;

  // Client-only voice tools. Each one is a named handler; nothing is built from
  // what the model said.
  const openSos = useCallback(() => setSosSignal((n) => n + 1), []);
  const dialContact = useCallback((contactId) => {
    const contact = contactsRef.current.find((c) => c.id === contactId);
    if (!contact) return null;
    // A tel: link is still the only thing that reliably reaches a person, and
    // the person presses dial themselves.
    window.location.href = `tel:${contact.phone}`;
    return { name: contact.name, phone: contact.phone };
  }, []);

  // Set once the wake word engine exists; used to make the closing sound come
  // out of the same speaker the wake sound did.
  const wakeSoundRef = useRef(null);

  const voice = useGeminiVoice({
    onOpenSos: openSos,
    onDialContact: dialContact,
    // A dose recorded by voice should appear on this screen straight away.
    onMutation: () => reload({ quiet: true }),
    // The conversation ended without a button press — either nothing was said
    // for a while, or they said goodbye. Say so out loud: otherwise the only
    // evidence is a status line somebody has put the phone down and is not
    // reading.
    onAutoStop: () => wakeSoundRef.current?.('stopped'),
  }, { timezone: self?.timezone || null });
  const {
    status: voiceStatus,
    active: voiceActive,
    start: startVoice,
    stop: stopVoice,
  } = voice;

  // Gamira speaking first when something has been waiting. She says one short
  // sentence out loud — no microphone, no session, no cost — and leaves a card.
  const { nudge, dismiss: dismissNudge } = useProactive({
    doses,
    reminders,
    ready: !loading && Boolean(seniorId),
  });

  // Hands-free activation. The engine holds the microphone and both audio
  // contexts open, so by the time "Gamira" is confirmed the only thing left to
  // do is start sending audio — see `useWakeWord` for how the Live API's
  // startup cost is taken off that path entirely.
  //
  // Arming needs a user gesture (microphone permission, and both AudioContexts
  // have to be resumed), so it happens on the first tap rather than on mount.
  // Read once: this is a development switch, not a setting.
  const [wakeDebug] = useState(
    () => new URLSearchParams(window.location.search).get('wake') === 'debug'
  );
  const wake = useWakeWord(voice, {
    lang: langCode[lang] || 'en-US',
    telemetry: wakeDebug,
  });
  const { resources: wakeResources } = wake;
  wakeSoundRef.current = wake.sound;

  const handleVoiceButton = useCallback(() => {
    if (voiceActive || voiceStatus === 'connecting') {
      stopVoice();
      return;
    }
    // Borrow the detector's microphone when it already has one, so pressing the
    // button does not open a second stream alongside it. (The detector arms
    // itself on the first touch anywhere — including this one.)
    startVoice({ resources: wakeResources() });
  }, [voiceActive, voiceStatus, stopVoice, startVoice, wakeResources]);

  const voiceLabels = {
    idle: { label: t('voiceIdle'), sub: t('notListening'), button: t('tapToTalk') },
    connecting: { label: t('voiceConnecting'), sub: t('voiceConnectingSub'), button: t('voiceConnecting') },
    listening: { label: t('voiceActive'), sub: t('listening'), button: t('voiceTapToStop') },
    speaking: { label: t('voiceActive'), sub: t('voiceSpeaking'), button: t('voiceTapToStop') },
    // Looking something up in the record, or waiting on a confirmation. The
    // microphone is paused while this is true.
    working: { label: t('voiceActive'), sub: 'Checking your record…', button: t('voiceTapToStop') },
    error: { label: t('voiceUnavailable'), sub: t('notListening'), button: t('tapToTalk') },
  };
  const labels = voiceLabels[voiceStatus] || voiceLabels.idle;

  // Whether Gamira is listening for its name is not something to leave people
  // guessing at — especially when the answer is "no, tap once first".
  const idleSub =
    voiceStatus === 'idle' && wake.listening ? 'Say “Gamira”, or tap to talk' : labels.sub;

  // Today's schedule: real dose events and the person's active reminders, in
  // the order the day happens rather than in two lists.
  const schedule = useMemo(
    () =>
      mergeSchedule(doses, reminders, {
        doseRow: (dose) => ({
          id: `dose-${dose.id}`,
          doseId: dose.id,
          time: clockTime(dose.scheduled_local_time),
          title: dose.medication_name || 'Medicine',
          subtitle: dose.dose_quantity || statusWord(dose.status),
          done: dose.status === 'taken',
          open: OPEN_DOSE_STATUSES.includes(dose.status),
          icon: Pill,
        }),
        reminderRow: (reminder) => ({
          id: `reminder-${reminder.id}`,
          doseId: null,
          time: clockTime(reminder.local_time),
          title: reminder.title,
          subtitle: reminder.instructions || '',
          done: false,
          open: false,
          icon: Bell,
        }),
      }),
    [doses, reminders]
  );

  // The next thing waiting for this person, by clock time.
  const next = useMemo(() => {
    const open = schedule.filter((row) => row.open);
    if (!open.length) return null;
    const upcoming = open.find((row) => (untilLocalTime(row.localTime) ?? -1) >= 0);
    return upcoming || open[0];
  }, [schedule]);

  const metricCards = useMemo(() => {
    const grouped = groupReadings(readings);
    return METRIC_CARDS.map((card) => readCard(card, grouped)).filter(Boolean).slice(0, 2);
  }, [readings]);

  const primaryContact = contacts.find((c) => c.is_primary) || contacts[0] || null;

  const confirm = async (row) => {
    setBusyId(row.doseId);
    try {
      await dosesApi.markTaken(row.doseId, { source: 'parent_app' });
      await reload();
      setActionError(null);
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const shownError = actionError || error;

  return (
    <>
      {/* Top bar */}
      <header className="relative flex items-center justify-end gap-3 px-5 pt-5 pb-3">
        <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 text-xl font-extrabold tracking-tight text-foreground">
          Gamira
        </span>
        <ThemeToggle />
        <Link
          to="/settings"
          aria-label={t('settings')}
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border bg-card text-foreground transition active:scale-95"
        >
          <SettingsIcon className="h-5 w-5" />
        </Link>
      </header>

      <div className="flex flex-col gap-6 px-5 pb-40">
        {/* Greeting */}
        <div className="flex flex-col gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {self?.preferred_name ? `Hello, ${self.preferred_name}` : t('greeting')}
            </h1>
            <p className="text-[15px] text-muted-foreground">{t('tapToTalk')}</p>
          </div>
          <GamiraStatusPill
            active={voiceActive || (voiceStatus === 'idle' && wake.listening)}
            label={labels.label}
            sublabel={idleSub}
          />
        </div>

        {/* Voice button */}
        <div className="flex flex-col items-center gap-3 py-4">
          <GamiraVoiceButton
            listening={voiceActive || voiceStatus === 'connecting'}
            onClick={handleVoiceButton}
            label={labels.button}
          />

          {voice.transcript && (
            <p className="max-w-[19rem] text-center text-[15px] leading-snug text-muted-foreground">
              {voice.transcript}
            </p>
          )}

          {voice.error && (
            <div className="flex w-full items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
              <p className="text-[13px] leading-snug text-foreground">{voice.error.message}</p>
            </div>
          )}
        </div>

        {shownError && (
          <div className="flex items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <p className="text-[15px] leading-snug text-foreground">{shownError}</p>
          </div>
        )}

        {!seniorId && !loading && (
          <GamiraCard>
            <p className="text-[15px] text-foreground">
              Your family has not added you in the Gamira dashboard yet. Once they
              do, your medicines and reminders appear here.
            </p>
          </GamiraCard>
        )}

        <ProactiveNudge
          nudge={nudge}
          onDismiss={dismissNudge}
          onTalk={() => {
            dismissNudge();
            if (!voiceActive) startVoice();
          }}
        />

        {/* Next thing waiting */}
        {next && (
          <GamiraCard className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/10">
              <Pill className="h-5 w-5 text-accent" />
            </div>
            <div className="flex-1">
              <p className="text-[13px] font-medium text-muted-foreground">{t('nextEventLabel')}</p>
              <p className="text-[15px] font-semibold text-foreground">{next.title}</p>
            </div>
            <span className="shrink-0 rounded-full bg-secondary px-3 py-1 text-[12px] font-semibold text-secondary-foreground">
              {describeMinutes(untilLocalTime(next.localTime))}
            </span>
          </GamiraCard>
        )}

        {/* Today's schedule */}
        <div className="flex flex-col gap-3">
          <GamiraSectionHeader title={t('todaysSchedule')} />
          {loading ? (
            <div className="flex flex-col gap-2.5">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 animate-pulse rounded-2xl border border-border bg-card" />
              ))}
            </div>
          ) : schedule.length === 0 ? (
            <GamiraCard>
              <p className="text-[15px] text-muted-foreground">Nothing is scheduled for today.</p>
            </GamiraCard>
          ) : (
            <div className="flex flex-col gap-2.5">
              {schedule.slice(0, 4).map((row) => (
                <div key={row.id} className="flex flex-col gap-2">
                  <GamiraScheduleCard
                    time={row.time}
                    title={row.title}
                    subtitle={row.subtitle}
                    done={row.done}
                    icon={row.icon}
                    onClick={() => navigate('/reminders')}
                  />
                  {row.open && (
                    <button
                      onClick={() => confirm(row)}
                      disabled={busyId === row.doseId}
                      className="flex h-14 items-center justify-center gap-2 rounded-2xl bg-primary text-lg font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-50"
                    >
                      <Check className="h-6 w-6" /> Taken
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Health snapshot */}
        <div className="flex flex-col gap-3">
          <GamiraSectionHeader title={t('healthOverview')} />
          {metricCards.length === 0 ? (
            <GamiraCard>
              <p className="text-[15px] text-muted-foreground">
                No readings have been recorded yet. Your family can add them in the
                Gamira dashboard.
              </p>
            </GamiraCard>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {metricCards.map((card) => (
                <GamiraMetricCard
                  key={card.id}
                  icon={card.icon}
                  iconBg={card.iconBg}
                  iconColor={card.iconColor}
                  label={labelFor(t, card)}
                  value={card.value}
                  unit={card.unit}
                  data={card.spark}
                  sparkColor={card.sparkColor}
                />
              ))}
            </div>
          )}
        </div>

        {/* SOS */}
        <div className="fixed bottom-0 left-1/2 z-10 flex w-full max-w-md -translate-x-1/2 flex-col items-center gap-2 bg-gradient-to-t from-background via-background to-background/0 px-5 pb-5 pt-8">
          <GamiraSOSButton
            openSignal={sosSignal}
            label={t('sos')}
            confirmTitle="Alert your family?"
            confirmMsg={
              primaryContact
                ? `Everyone in your family sees this in their Gamira app, and you can then call ${primaryContact.name} on ${primaryContact.phone}. Gamira does not contact emergency services.`
                : 'Everyone in your family sees this in their Gamira app. No emergency contact is saved yet, so Gamira cannot offer a call — for an emergency, dial your local emergency number.'
            }
            yesLabel="Alert my family"
            cancelLabel={t('cancel')}
            callLabel={primaryContact ? `Call ${primaryContact.name}` : ''}
            onAlert={
              seniorId ? () => sosApi.raise(seniorId, { source: 'parent_app' }) : null
            }
            onCall={
              primaryContact
                ? // A tel: link is still the only thing that reliably reaches a
                  // person. The alert above is visible in the family's app; it
                  // does not ring anyone's phone.
                  () => {
                    window.location.href = `tel:${primaryContact.phone}`;
                  }
                : null
            }
          />
        </div>
      </div>

      {/* Every voice action that changes something passes through here first. */}
      <VoiceConfirmDialog
        open={Boolean(voice.confirmation)}
        prompt={voice.confirmation?.prompt}
        busy={voice.confirmBusy}
        onConfirm={voice.acceptConfirmation}
        onCancel={voice.rejectConfirmation}
      />

      {wakeDebug && <WakeWordDebug wake={wake} />}
    </>
  );
}

function labelFor(t, card) {
  const translated = t(card.labelKey);
  return translated === card.labelKey ? card.fallbackLabel : translated;
}

function statusWord(status) {
  const words = {
    due: 'Due',
    reminded: 'Reminded',
    late: 'Late',
    missed: 'Missed',
    taken: 'Taken',
    skipped: 'Skipped',
    cancelled: 'Cancelled',
  };
  return words[status] || status;
}
