import { useState } from 'react';
import { Check } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { useT, useI18n, supportedLanguages, nativeName } from '@/lib/i18n';

export default function Language() {
  const t = useT();
  const { lang, changeLanguage } = useI18n();
  const [selected, setSelected] = useState(lang || 'English');
  const [saved, setSaved] = useState(false);

  const save = () => {
    changeLanguage(selected);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('language')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-5 text-base text-muted-foreground">{t('languageSubtitle')}</p>

        {saved && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-green-500/30 bg-green-500/10 p-3 text-green-600">
            <Check className="h-5 w-5" />
            <span className="text-base font-medium">{t('languageSaved', nativeName(selected))}</span>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {supportedLanguages.map((l) => {
            const active = selected === l.name;
            return (
              <button
                key={l.name}
                type="button"
                onClick={() => setSelected(l.name)}
                className={`flex w-full items-center justify-between rounded-2xl border p-4 text-left transition active:scale-[0.98] ${active ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}
              >
                <div>
                  <p className="text-2xl font-bold text-foreground">{l.native}</p>
                  <p className="text-base text-muted-foreground">{l.name}</p>
                </div>
                <span className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${active ? 'border-primary bg-primary text-white' : 'border-border'}`}>
                  {active && <Check className="h-5 w-5" strokeWidth={3} />}
                </span>
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={save}
          className="mt-6 h-14 w-full rounded-2xl bg-primary text-base font-semibold text-primary-foreground transition active:scale-95"
        >
          {t('saveLanguage')}
        </button>
      </main>
    </div>
  );
}
