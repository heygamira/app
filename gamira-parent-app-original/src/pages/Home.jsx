import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, Bell, Check, Pill, Settings as SettingsIcon } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useVoice } from '@/lib/VoiceContext';
import { mergeSchedule, minutesUntil, orderTodaySchedule } from '@/lib/schedule';
import { doses as dosesApi, alerts as alertsApi, sos as sosApi } from '@/api/gamiraClient';
import {
  METRIC_CARDS,
  OPEN_DOSE_STATUSES,
  clockTime,
  describeMinutes,
  groupReadings,
  readCard,
} from '@/api/parentData';
import { useSeniorCare } from '@/lib/useSeniorCare';
import GamiraVoiceButton from '@/components/gamira/GamiraVoiceButton';
import GamiraStatusPill from '@/components/gamira/GamiraStatusPill';
import ProactiveNudge from '@/components/gamira/ProactiveNudge';
import WellbeingCheckCard from '@/components/gamira/WellbeingCheckCard';
import VoiceTranscript from '@/components/gamira/VoiceTranscript';
import GamiraCard from '@/components/gamira/GamiraCard';
import GamiraScheduleCard from '@/components/gamira/GamiraScheduleCard';
import GamiraSectionHeader from '@/components/gamira/GamiraSectionHeader';
import GamiraMetricCard from '@/components/gamira/GamiraMetricCard';
import GamiraSOSButton from '@/components/gamira/GamiraSOSButton';
import ThemeToggle from '@/components/ThemeToggle';

// Long enough to say "cancel" or reach a large button; short enough that
// somebody who really needs help is not waiting through it.
const SOS_COUNTDOWN_SECONDS = 5;

export default function Home() {
  const { t } = useI18n();
  const navigate = useNavigate();

  // The voice session, the wake word and anything Gamira decided to say first
  // all live above this page now, so they survive navigating away from it.
  const {
    voice,
    wake,
    status: voiceStatus,
    active: voiceActive,
    talk,
    speakFirst,
    toggle: toggleVoice,
    register,
    nudge,
    dismissNudge,
    pendingCheck,
    answerCheck,
    self,
    seniorId,
    doses,
    reminders,
    contacts,
    loading,
    error,
    reload,
  } = useVoice();

  // Only the readings, which are this screen's alone. Everything else comes
  // from the provider, which already loads it for Gamira — asking twice would
  // double the requests and let the two copies disagree about the same day.
  const { readings } = useSeniorCare({ readings: true });

  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [checkBusy, setCheckBusy] = useState(false);
  // Bumped to open the real SOS dialog. The assistant's `prepare_sos` ends up
  // here: it opens the screen and starts the countdown.
  const [sosSignal, setSosSignal] = useState(0);
  const sosRef = useRef(null);

  // What this screen can do, published for voice tools to reach. Named
  // handlers, never anything built from what the model said.
  useEffect(
    () =>
      register({
        openSos: () => setSosSignal((n) => n + 1),
        cancelSosCountdown: () => sosRef.current?.cancelCountdown() ?? false,
        // An alert withdrawn out loud. The dialog on this screen is still
        // saying "your family knows", which stopped being true the moment the
        // backend cancelled it.
        sosWithdrawn: () => sosRef.current?.withdrawn() ?? false,
        openDose: () => navigate('/reminders'),
        openReminder: () => navigate('/reminders'),
      }),
    [register, navigate]
  );

  const voiceLabels = {
    idle: { label: t('voiceIdle'), sub: t('notListening'), button: t('tapToTalk') },
    connecting: { label: t('voiceConnecting'), sub: t('voiceConnectingSub'), button: t('voiceConnecting') },
    listening: { label: t('voiceActive'), sub: t('listening'), button: t('voiceTapToStop') },
    speaking: { label: t('voiceActive'), sub: t('voiceSpeaking'), button: t('voiceTapToStop') },
    // Looking something up in the record, or waiting on a confirmation.
    working: { label: t('voiceActive'), sub: 'Checking your record…', button: t('voiceTapToStop') },
    error: { label: t('voiceUnavailable'), sub: t('notListening'), button: t('tapToTalk') },
  };
  const labels = voiceLabels[voiceStatus] || voiceLabels.idle;

  // Whether Gamira is listening for its name is not something to leave people
  // guessing at — especially when the answer is "no".
  const idleSub =
    voiceStatus === 'idle' && wake.listening ? 'Say “Gamira”, or tap to talk' : labels.sub;

  // What the button looks like, which is the app's only status light.
  const buttonState =
    voiceStatus === 'idle' || voiceStatus === 'error'
      ? wake.listening
        ? 'wake'
        : 'off'
      : voiceStatus;

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

  // Today's schedule, next-thing-first: whatever is still ahead, soonest
  // first, then whatever has already gone by — with anything past and marked
  // done dropped, since it happened and does not need to keep the top of the
  // list. `self.timezone` is the senior's own, not this device's.
  const orderedSchedule = useMemo(
    () => orderTodaySchedule(schedule, self?.timezone),
    [schedule, self?.timezone]
  );

  // The next thing waiting for this person, by clock time.
  const next = useMemo(() => {
    const open = schedule.filter((row) => row.open);
    if (!open.length) return null;
    const upcoming = open.find((row) => (minutesUntil(row.localTime, self?.timezone) ?? -1) >= 0);
    return upcoming || open[0];
  }, [schedule, self?.timezone]);

  const metricCards = useMemo(() => {
    const grouped = groupReadings(readings);
    return METRIC_CARDS.map((card) => readCard(card, grouped)).filter(Boolean).slice(0, 2);
  }, [readings]);

  const primaryContact = contacts.find((c) => c.is_primary) || contacts[0] || null;

  const confirm = async (doseId) => {
    setBusyId(doseId);
    try {
      await dosesApi.markTaken(doseId, { source: 'parent_app' });
      await reload();
      setActionError(null);
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const raiseSos = useCallback(
    () => (seniorId ? sosApi.raise(seniorId, { source: 'parent_app' }) : null),
    [seniorId]
  );

  // Cancelling keeps the row and tells the family it was withdrawn. A red
  // alert that silently disappears is worse for them than the false alarm was.
  const cancelSosAlert = useCallback(
    (alertId) => alertsApi.cancel(alertId, 'They said they are alright.'),
    []
  );

  /**
   * Gamira says the countdown out loud, so it can be stopped by voice.
   *
   * Reaching the screen is exactly what pressing SOS says they may not be able
   * to do, so the way out has to be sayable. Routed through `speakFirst`, which
   * joins an open conversation if there is one and opens a session if there is
   * not — this used to be `briefInto(...) || talk(...)`, and `talk` is async,
   * so the `||` was testing a promise. It was always truthy, the fallback never
   * ran, and with no session open she simply said nothing.
   *
   * These three are memoised because `GamiraSOSButton` counts down on a timer:
   * a new identity on every render used to restart that timer and re-open the
   * dialog. The component holds them in refs now as well — belt and braces on
   * the one control where a bug is an emergency.
   */
  const announceCountdown = useCallback(
    (seconds) =>
      speakFirst(
        '[The emergency screen has just opened and is counting down from ' +
          `${seconds} seconds. Say so in one short sentence, and tell them to ` +
          'say "cancel" if they are alright. Then stop and listen. If they say ' +
          'cancel, or that they are alright, use cancel_sos_countdown straight ' +
          'away.]'
      ),
    [speakFirst]
  );

  const onAnswerCheck = useCallback(
    async (alright) => {
      setCheckBusy(true);
      try {
        await answerCheck(alright);
      } finally {
        setCheckBusy(false);
      }
    },
    [answerCheck]
  );

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

        {/* Voice button and the conversation itself */}
        <div className="flex flex-col items-center gap-3 py-4">
          <GamiraVoiceButton
            state={buttonState}
            onClick={toggleVoice}
            label={labels.button}
          />

          <VoiceTranscript
            turns={voice.turns}
            thinking={voiceStatus === 'working' || voiceStatus === 'connecting'}
          />

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

        {/* A watch flagged something and Gamira has asked about it out loud.
            This is the way to answer for anybody who would rather not speak. */}
        <WellbeingCheckCard
          check={pendingCheck}
          busy={checkBusy}
          onAnswer={onAnswerCheck}
        />

        <ProactiveNudge
          nudge={nudge}
          busy={busyId === nudge?.doseId}
          onDismiss={dismissNudge}
          // A dose is recorded; anything else is just acknowledged. There is
          // nothing to write down about having had a glass of water, and
          // completing a daily reminder would end the daily reminder.
          onDone={
            nudge?.doseId
              ? () => confirm(nudge.doseId)
              : () => dismissNudge()
          }
        />

        {/* Next thing waiting — and the one large "Taken" button, in the one
            place where a large button is genuinely wanted. */}
        {next && (
          <GamiraCard className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/10">
                <Pill className="h-5 w-5 text-accent" />
              </div>
              <div className="flex-1">
                <p className="text-[13px] font-medium text-muted-foreground">{t('nextEventLabel')}</p>
                <p className="text-[15px] font-semibold text-foreground">{next.title}</p>
              </div>
              <span className="shrink-0 rounded-full bg-secondary px-3 py-1 text-[12px] font-semibold text-secondary-foreground">
                {describeMinutes(minutesUntil(next.localTime, self?.timezone))}
              </span>
            </div>
            {next.doseId && (
              <button
                onClick={() => confirm(next.doseId)}
                disabled={busyId === next.doseId}
                className="flex h-14 items-center justify-center gap-2 rounded-2xl bg-primary text-lg font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-50"
              >
                <Check className="h-6 w-6" /> Taken
              </button>
            )}
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
          ) : orderedSchedule.length === 0 ? (
            <GamiraCard>
              <p className="text-[15px] text-muted-foreground">Nothing is scheduled for today.</p>
            </GamiraCard>
          ) : (
            <div className="flex flex-col gap-2.5">
              {orderedSchedule.slice(0, 4).map((row) => (
                <GamiraScheduleCard
                  key={row.id}
                  time={row.time}
                  title={row.title}
                  subtitle={row.subtitle}
                  done={row.done}
                  icon={row.icon}
                  onClick={() => navigate('/reminders')}
                  // Inside the card, beside the medicine it records — rather
                  // than a full-width bar underneath, where the last one read
                  // as a page action belonging to nothing.
                  action={
                    row.open ? (
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          confirm(row.doseId);
                        }}
                        disabled={busyId === row.doseId}
                        aria-label={`Record ${row.title} as taken`}
                        className="flex h-11 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[15px] font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-50"
                      >
                        <Check className="h-5 w-5" /> Taken
                      </button>
                    ) : null
                  }
                />
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
                  stale={card.stale}
                />
              ))}
            </div>
          )}
        </div>

        {/* SOS */}
        <div className="fixed bottom-0 left-1/2 z-10 flex w-full max-w-md -translate-x-1/2 flex-col items-center gap-2 bg-gradient-to-t from-background via-background to-background/0 px-5 pb-5 pt-8">
          <GamiraSOSButton
            controlRef={sosRef}
            openSignal={sosSignal}
            countdownSeconds={SOS_COUNTDOWN_SECONDS}
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
            onAlert={raiseSos}
            onCancelAlert={cancelSosAlert}
            onCountdownStart={announceCountdown}
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
