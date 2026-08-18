import { useState } from 'react';
import { AlertCircle, Bell, Check, SkipForward } from 'lucide-react';
import GamiraSectionHeader from '@/components/gamira/GamiraSectionHeader';
import GamiraCard from '@/components/gamira/GamiraCard';
import { useT } from '@/lib/i18n';
import { sortableTime } from '@/lib/schedule';
import { useSeniorCare } from '@/lib/useSeniorCare';
import { doses as dosesApi } from '@/api/gamiraClient';
import { OPEN_DOSE_STATUSES, clockTime } from '@/api/parentData';

export default function Reminders() {
  const t = useT();
  const { doses, reminders, loading, error, seniorId, reload } = useSeniorCare({
    doses: true,
    reminders: true,
  });

  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);

  // Confirming is idempotent in the client and on the server, so a second tap
  // on a slow connection cannot record a second dose.
  const record = async (dose, outcome) => {
    setBusyId(dose.id);
    try {
      if (outcome === 'taken') await dosesApi.markTaken(dose.id);
      else await dosesApi.markSkipped(dose.id);
      await reload();
      setActionError(null);
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusyId(null);
    }
  };

  // Doses and routines stay in separate sections here on purpose: a dose has
  // Taken and Skip against it and a routine does not, and mixing them would put
  // rows with buttons and rows without into one column. Each section is still
  // ordered by the clock.
  const byTime = (a, b) => sortableTime(a).localeCompare(sortableTime(b));
  const open = doses
    .filter((dose) => OPEN_DOSE_STATUSES.includes(dose.status))
    .sort((a, b) => byTime(a.scheduled_local_time, b.scheduled_local_time));
  const done = doses.filter((dose) => ['taken', 'skipped'].includes(dose.status));
  const routines = reminders
    .filter((reminder) => reminder.status === 'active')
    .sort((a, b) => byTime(a.local_time, b.local_time));

  const shownError = actionError || error;

  return (
    <>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-background/90 px-5 pt-5 pb-3 backdrop-blur">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{t('remindersTitle')}</h1>
      </header>

      <div className="flex flex-col gap-6 px-5 py-5">
        <p className="text-[15px] text-muted-foreground">{t('remindersSubtitle')}</p>

        {shownError && (
          <div className="flex items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <p className="text-[15px] leading-snug text-foreground">{shownError}</p>
          </div>
        )}

        {loading ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-28 animate-pulse rounded-2xl border border-border bg-card" />
            ))}
          </div>
        ) : !seniorId ? (
          <GamiraCard>
            <p className="text-[15px] text-foreground">
              Ask your family to add you in the Gamira dashboard.
            </p>
          </GamiraCard>
        ) : (
          <>
            <div className="flex flex-col gap-3">
              <GamiraSectionHeader title={t('todaySection')} />
              {open.length === 0 ? (
                <GamiraCard>
                  <p className="text-[15px] text-muted-foreground">
                    Nothing is waiting right now.
                  </p>
                </GamiraCard>
              ) : (
                open.map((dose) => (
                  <div
                    key={dose.id}
                    className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4 shadow-sm"
                  >
                    <div>
                      <p className="text-lg font-semibold text-foreground">{dose.medication_name}</p>
                      <p className="text-[15px] text-muted-foreground">
                        {clockTime(dose.scheduled_local_time)}
                        {dose.dose_quantity ? ` · ${dose.dose_quantity}` : ''}
                      </p>
                      {dose.status === 'missed' && (
                        <p className="text-[15px] font-medium text-destructive">Missed</p>
                      )}
                      {dose.status === 'late' && (
                        <p className="text-[15px] font-medium text-amber-600">Late</p>
                      )}
                    </div>
                    {/* Large, clearly separated targets: this is the screen an
                        older person uses under time pressure. */}
                    <div className="flex gap-3">
                      <button
                        onClick={() => record(dose, 'taken')}
                        disabled={busyId === dose.id}
                        className="flex h-14 flex-1 items-center justify-center gap-2 rounded-xl bg-primary text-lg font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-50"
                      >
                        <Check className="h-6 w-6" /> Taken
                      </button>
                      <button
                        onClick={() => record(dose, 'skipped')}
                        disabled={busyId === dose.id}
                        className="flex h-14 w-32 items-center justify-center gap-2 rounded-xl border border-border bg-background text-lg font-semibold text-foreground transition active:scale-95 disabled:opacity-50"
                      >
                        <SkipForward className="h-5 w-5" /> Skip
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>

            {routines.length > 0 && (
              <div className="flex flex-col gap-3">
                <GamiraSectionHeader title="Your routines" />
                {routines.map((reminder) => (
                  <div
                    key={reminder.id}
                    className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4"
                  >
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent/10">
                      <Bell className="h-5 w-5 text-accent" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-lg font-semibold text-foreground">{reminder.title}</p>
                      <p className="text-[15px] text-muted-foreground">
                        {[clockTime(reminder.local_time), reminder.instructions]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {done.length > 0 && (
              <div className="flex flex-col gap-3">
                <GamiraSectionHeader title={t('completedSection')} />
                {done.map((dose) => (
                  <div
                    key={dose.id}
                    className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4"
                  >
                    <Check className="h-6 w-6 text-primary" />
                    <div className="flex-1">
                      <p className="text-lg font-semibold text-foreground">{dose.medication_name}</p>
                      <p className="text-[15px] text-muted-foreground">
                        {clockTime(dose.scheduled_local_time)} · {dose.status}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
