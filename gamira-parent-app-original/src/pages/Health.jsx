import { useMemo } from 'react';
import { AlertCircle, HeartPulse } from 'lucide-react';
import GamiraMetricCard from '@/components/gamira/GamiraMetricCard';
import GamiraSectionHeader from '@/components/gamira/GamiraSectionHeader';
import GamiraCard from '@/components/gamira/GamiraCard';
import { useT } from '@/lib/i18n';
import { useSeniorCare } from '@/lib/useSeniorCare';
import { METRIC_CARDS, groupReadings, readCard } from '@/api/parentData';

export default function Health() {
  const t = useT();
  const { readings, loading, error, seniorId } = useSeniorCare({ readings: true });

  const { recorded, missing } = useMemo(() => {
    const grouped = groupReadings(readings);
    const cards = METRIC_CARDS.map((card) => ({ card, view: readCard(card, grouped) }));
    return {
      recorded: cards.filter((entry) => entry.view).map((entry) => entry.view),
      missing: cards.filter((entry) => !entry.view).map((entry) => entry.card),
    };
  }, [readings]);

  return (
    <>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-background/90 px-5 pt-5 pb-3 backdrop-blur">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{t('healthTitle')}</h1>
      </header>

      <div className="flex flex-col gap-6 px-5 py-5">
        <p className="text-[15px] text-muted-foreground">{t('healthSubtitle')}</p>

        {error && (
          <div className="flex items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <p className="text-[15px] leading-snug text-foreground">{error}</p>
          </div>
        )}

        {loading ? (
          <div className="grid grid-cols-2 gap-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-32 animate-pulse rounded-2xl border border-border bg-card" />
            ))}
          </div>
        ) : !seniorId ? (
          <GamiraCard>
            <p className="text-[15px] text-foreground">
              Ask your family to add you in the Gamira dashboard.
            </p>
          </GamiraCard>
        ) : recorded.length === 0 ? (
          <GamiraCard className="flex flex-col items-center gap-3 py-10 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
              <HeartPulse className="h-8 w-8 text-primary" />
            </div>
            {/* Nothing invented here: this screen used to show 72 bpm and
                120/80 for everyone, whether or not anyone had measured them. */}
            <p className="text-[15px] text-muted-foreground">
              No readings have been recorded yet. Your family can add them in the
              Gamira dashboard, and they will appear here.
            </p>
          </GamiraCard>
        ) : (
          <>
            <div className="flex flex-col gap-3">
              <GamiraSectionHeader title={t('healthOverview')} />
              <div className="grid grid-cols-2 gap-3">
                {recorded.map((card) => (
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
              <p className="text-[13px] text-muted-foreground">
                Gamira shows what has been recorded. It does not decide whether a
                reading is healthy — ask a doctor about anything that worries you.
              </p>
            </div>

            {missing.length > 0 && (
              <div className="flex flex-col gap-3">
                <GamiraSectionHeader title="Not recorded yet" />
                <GamiraCard className="flex flex-col gap-2">
                  {missing.map((card) => (
                    <div key={card.id} className="flex items-center justify-between">
                      <span className="text-[15px] text-foreground">{labelFor(t, card)}</span>
                      <span className="text-[13px] text-muted-foreground">—</span>
                    </div>
                  ))}
                </GamiraCard>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

function labelFor(t, card) {
  const translated = t(card.labelKey);
  return translated === card.labelKey ? card.fallbackLabel : translated;
}
