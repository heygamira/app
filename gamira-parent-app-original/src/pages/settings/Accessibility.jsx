import { useState } from 'react';
import { Check } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import Toggle from '@/components/Toggle';
import { getSettings, updateSettings, applyAccessibility } from '@/lib/userSettings';
import { useT } from '@/lib/i18n';

const sizes = ['Small', 'Standard', 'Large', 'Extra Large'];
const sizeKey = { Small: 'small', Standard: 'standard', Large: 'large', 'Extra Large': 'extraLarge' };
const sizePreviewClass = { Small: 'text-base', Standard: 'text-lg', Large: 'text-xl', 'Extra Large': 'text-2xl' };

export default function Accessibility() {
  const t = useT();
  const a = getSettings().accessibility || {};
  const [textSize, setTextSize] = useState(a.textSize || 'Standard');
  const [voiceAssistance, setVoiceAssistance] = useState(!!a.voiceAssistance);
  const [saved, setSaved] = useState(false);

  const saveAll = (next) => {
    updateSettings({ accessibility: next });
    applyAccessibility();
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const changeSize = (s) => {
    setTextSize(s);
    saveAll({ textSize: s, voiceAssistance });
  };
  const changeVoice = (v) => {
    setVoiceAssistance(v);
    saveAll({ textSize, voiceAssistance: v });
  };

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('accessibilityTitle')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-5 text-base text-muted-foreground">{t('accessibilitySubtitle')}</p>

        {saved && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-green-500/30 bg-green-500/10 p-3 text-green-600">
            <Check className="h-5 w-5" />
            <span className="text-base font-medium">{t('saved')}</span>
          </div>
        )}

        <h2 className="mb-3 text-lg font-bold text-foreground">{t('textSize')}</h2>
        <div className="mb-6 flex flex-col gap-2">
          {sizes.map((s) => {
            const active = textSize === s;
            return (
              <button
                key={s}
                type="button"
                onClick={() => changeSize(s)}
                className={`flex items-center justify-between rounded-2xl border p-4 transition active:scale-[0.98] ${active ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}
              >
                <span className={`font-semibold text-foreground ${sizePreviewClass[s]}`}>{t(sizeKey[s])}</span>
                <span className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${active ? 'border-primary bg-primary text-white' : 'border-border'}`}>
                  {active && <Check className="h-5 w-5" strokeWidth={3} />}
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex flex-col gap-3">
          <ToggleRow title={t('voiceAssistance')} desc={t('voiceAssistanceDesc')} checked={voiceAssistance} onChange={changeVoice} />
        </div>
      </main>
    </div>
  );
}

function ToggleRow({ title, desc, checked, onChange }) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-border bg-card p-4">
      <div className="flex-1 pr-3">
        <p className="text-lg font-semibold text-foreground">{title}</p>
        <p className="text-sm text-muted-foreground">{desc}</p>
      </div>
      <Toggle checked={checked} onChange={onChange} ariaLabel={title} />
    </div>
  );
}
