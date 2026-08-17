import { useState } from 'react';
import { Play, Check, Volume2 } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { getSettings, updateSettings } from '@/lib/userSettings';
import { useT } from '@/lib/i18n';

// How Gamira hears its name. 'auto' prefers the trained on-device detector and
// falls back to the browser's own speech recognition when it cannot run; the
// other two pin one engine, which is what makes an A/B on a real phone possible
// while the detector is still being improved.
const wakeEngines = [
  { key: 'auto', label: 'Automatic', desc: 'On-device, with a fallback' },
  { key: 'onnx', label: 'On device', desc: 'Nothing leaves the phone until Gamira is heard' },
  { key: 'speech', label: 'Browser', desc: 'Chrome and Safari only; sends what it hears to Google' },
];

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
  const [wake, setWake] = useState(() => ({
    enabled: true,
    engine: 'auto',
    sensitivityOffset: 0,
    chime: true,
    preconnect: true,
    ...(s.wakeWord || {}),
  }));

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
    // The whole wake-word object every time: settings are merged one level
    // deep, so writing a partial one would drop the keys it left out.
    updateSettings({ voice: selected, speakingSpeed: speed, wakeWord: wake });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const patchWake = (patch) => setWake((prev) => ({ ...prev, ...patch }));

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

        <div className="mt-8">
          <h2 className="mb-1 text-lg font-bold text-foreground">Saying “Gamira”</h2>
          <p className="mb-3 text-sm text-muted-foreground">
            Gamira can start listening when you say its name, so you do not have to
            press anything. This only works while the app is open on screen.
          </p>

          <button
            type="button"
            onClick={() => patchWake({ enabled: !wake.enabled })}
            className={`flex h-14 w-full items-center justify-between rounded-2xl border px-4 text-base font-semibold transition active:scale-95 ${
              wake.enabled ? 'border-primary bg-primary/5 text-foreground' : 'border-border bg-card text-foreground'
            }`}
          >
            <span>Listen for my name</span>
            <span
              className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${
                wake.enabled ? 'border-primary bg-primary text-white' : 'border-border'
              }`}
            >
              {wake.enabled && <Check className="h-5 w-5" strokeWidth={3} />}
            </span>
          </button>

          {wake.enabled && (
            <>
              <button
                type="button"
                onClick={() => patchWake({ chime: !wake.chime })}
                className={`mt-2 flex h-14 w-full items-center justify-between rounded-2xl border px-4 text-base font-semibold transition active:scale-95 ${
                  wake.chime ? 'border-primary bg-primary/5 text-foreground' : 'border-border bg-card text-foreground'
                }`}
              >
                <span>Make a sound when it hears me</span>
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-full border-2 ${
                    wake.chime ? 'border-primary bg-primary text-white' : 'border-border'
                  }`}
                >
                  {wake.chime && <Check className="h-5 w-5" strokeWidth={3} />}
                </span>
              </button>

              <h3 className="mb-2 mt-6 text-base font-semibold text-foreground">How it listens</h3>
              <div className="flex flex-col gap-2">
                {wakeEngines.map((option) => {
                  const active = wake.engine === option.key;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => patchWake({ engine: option.key })}
                      className={`flex items-center justify-between rounded-2xl border p-4 text-left transition active:scale-95 ${
                        active ? 'border-primary bg-primary/5' : 'border-border bg-card'
                      }`}
                    >
                      <div>
                        <p className="text-base font-semibold text-foreground">{option.label}</p>
                        <p className="text-sm text-muted-foreground">{option.desc}</p>
                      </div>
                      <span
                        className={`ml-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 ${
                          active ? 'border-primary bg-primary text-white' : 'border-border'
                        }`}
                      >
                        {active && <Check className="h-5 w-5" strokeWidth={3} />}
                      </span>
                    </button>
                  );
                })}
              </div>

              <h3 className="mb-2 mt-6 text-base font-semibold text-foreground">
                How easily it wakes up
              </h3>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Careful', value: 0.03 },
                  { label: 'Normal', value: 0 },
                  { label: 'Eager', value: -0.08 },
                ].map((option) => {
                  const active = (wake.sensitivityOffset || 0) === option.value;
                  return (
                    <button
                      key={option.label}
                      type="button"
                      onClick={() => patchWake({ sensitivityOffset: option.value })}
                      className={`h-14 rounded-2xl border text-base font-semibold transition active:scale-95 ${
                        active ? 'border-primary bg-primary text-white' : 'border-border bg-card text-foreground'
                      }`}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                “Eager” answers more often but is more likely to wake up when nobody
                called it.
              </p>
            </>
          )}
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
