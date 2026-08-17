import { useState } from 'react';
import { Check } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { getStoredTheme, setTheme } from '@/lib/theme';
import { useT } from '@/lib/i18n';

export default function Theme() {
  const t = useT();
  const [theme, setThemeState] = useState(getStoredTheme());

  const options = [
    { value: 'system', label: t('system') },
    { value: 'light', label: t('light') },
    { value: 'dark', label: t('dark') },
  ];

  const choose = (v) => {
    setTheme(v);
    setThemeState(v);
  };

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('themeTitle')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-6 text-base text-muted-foreground">{t('themeSubtitle')}</p>
        <div className="flex flex-col gap-3">
          {options.map((o) => (
            <button
              key={o.value}
              onClick={() => choose(o.value)}
              className="flex h-16 items-center justify-between rounded-2xl border border-border bg-card px-5 shadow-sm transition active:scale-[0.99]"
            >
              <span className="text-lg font-semibold text-foreground">{o.label}</span>
              {theme === o.value && <Check className="h-6 w-6 text-primary" strokeWidth={3} />}
            </button>
          ))}
        </div>
      </main>
    </div>
  );
}
