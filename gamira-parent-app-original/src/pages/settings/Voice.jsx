import { useState } from 'react';
import { Play, Check, Volume2 } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { getSettings, updateSettings } from '@/lib/userSettings';
import { useT } from '@/lib/i18n';

const voices = [
  { name: 'Warm Female', key: 'warmFemale', desc: 'friendlyCaring' },
  { name: 'Calm Female', key: 'calmFemale', desc: 'gentleSoothing' },
  { name: 'Warm Male', key: 'warmMale', desc: 'kindWelcoming' },
  { name: 'Calm Male', key: 'calmMale', desc: 'steadyReassuring' },
];

const speeds = ['Slow', 'Normal', 'Fast'];
const speedKey = { Slow: 'slow', Normal: 'standard', Fast: 'fast' };
const rateMap = { Slow: 0.8, Normal: 1, Fast: 1.3 };

export default function Voice() {
  const t = useT();
  const s = getSettings();
  const [selected, setSelected] = useState(s.voice || 'Warm Female');
  const [speed, setSpeed] = useState(s.speakingSpeed || 'Normal');
  const [playing, setPlaying] = useState(null);
  const [saved, setSaved] = useState(false);

  const preview = (name) => {
    setPlaying(name);
    try {
      const utter = new SpeechSynthesisUtterance(t('voicePreview'));
      utter.rate = rateMap[speed] || 1;
      const female = /Female/i.test(name);
      const list = window.speechSynthesis.getVoices();
      const match = list.find((v) => /female/i.test(v.name) === female);
      if (match) utter.voice = match;
      utter.onend = () => setPlaying(null);
      utter.onerror = () => setPlaying(null);
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utter);
    } catch {
      setPlaying(null);
    }
    setTimeout(() => setPlaying((p) => (p === name ? null : p)), 4000);
  };

  const save = () => {
    updateSettings({ voice: selected, speakingSpeed: speed });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('voiceTitle')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-5 text-base text-muted-foreground">{t('voiceSubtitle')}</p>

        {saved && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-green-500/30 bg-green-500/10 p-3 text-green-600">
            <Check className="h-5 w-5" />
            <span className="text-base font-medium">{t('voiceSaved')}</span>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {voices.map((v) => {
            const active = selected === v.name;
            return (
              <div key={v.name} className={`rounded-2xl border p-4 ${active ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}>
                <button type="button" onClick={() => setSelected(v.name)} className="flex w-full items-center justify-between text-left">
                  <div>
                    <p className="text-lg font-semibold text-foreground">{t(v.key)}</p>
                    <p className="text-sm text-muted-foreground">{t(v.desc)}</p>
                  </div>
                  <span className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${active ? 'border-primary bg-primary text-white' : 'border-border'}`}>
                    {active && <Check className="h-5 w-5" strokeWidth={3} />}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => preview(v.name)}
                  className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary/10 text-base font-semibold text-primary transition active:scale-95"
                >
                  {playing === v.name ? <Volume2 className="h-5 w-5" /> : <Play className="h-5 w-5" />}
                  {playing === v.name ? t('playing') : t('play')}
                </button>
              </div>
            );
          })}
        </div>

        <div className="mt-8">
          <h2 className="mb-3 text-lg font-bold text-foreground">{t('speakingSpeed')}</h2>
          <div className="grid grid-cols-3 gap-2">
            {speeds.map((sp) => {
              const active = speed === sp;
              return (
                <button
                  key={sp}
                  type="button"
                  onClick={() => setSpeed(sp)}
                  className={`h-14 rounded-2xl border text-base font-semibold transition active:scale-95 ${active ? 'border-primary bg-primary text-white' : 'border-border bg-card text-foreground'}`}
                >
                  {t(speedKey[sp])}
                </button>
              );
            })}
          </div>
        </div>

        <button
          type="button"
          onClick={save}
          className="mt-8 h-14 w-full rounded-2xl bg-primary text-base font-semibold text-primary-foreground transition active:scale-95"
        >
          {t('saveVoice')}
        </button>
      </main>
    </div>
  );
}
