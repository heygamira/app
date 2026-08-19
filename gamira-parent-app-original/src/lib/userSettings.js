const KEY = 'gamira-user-settings';

const defaults = {
  profile: { name: '', age: '', phone: '' },
  language: 'English',
  voice: 'Warm Female',
  speakingSpeed: 'Normal',
  family: [],
  // Hands-free activation. `engine: 'auto'` prefers the trained on-device
  // detector and falls back to the browser's speech recognition; pin it to
  // 'onnx' or 'speech' to compare the two on a real device while the model is
  // still being improved. `sensitivityOffset` shifts the detector's threshold:
  // negative catches more and false-triggers more.
  wakeWord: {
    enabled: true,
    engine: 'auto',
    sensitivityOffset: 0,
    // Which sound plays when Gamira hears its name. 'off' is silent.
    sound: 'chime',
    preconnect: true,
  },
  // A conversation nobody is having still streams the microphone and is still
  // billed for it, so it closes itself after this long with no activity.
  // 0 means never.
  voiceSession: { autoStopSeconds: 60 },
  // Whether Gamira may speak first when something has been waiting a while.
  // On by default on purpose: a reminder that has to be discovered in Settings
  // will not reach the person who most needs it. Speaking costs nothing and
  // opens no microphone — see `lib/useProactive.js`.
  proactive: { enabled: true },
  emergency: { primary: null, others: [], shareLocation: false },
  accessibility: { textSize: 'Standard', highContrast: false, reduceMotion: false, voiceAssistance: false },
};

export function getSettings() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...defaults };
    const parsed = JSON.parse(raw);
    return { ...defaults, ...parsed };
  } catch {
    return { ...defaults };
  }
}

export function saveSettings(data) {
  try {
    localStorage.setItem(KEY, JSON.stringify(data));
  } catch {
    /* ignore */
  }
  // localStorage is not reactive, and `storage` only fires in *other* tabs —
  // so anything reading a setting in this one had no way to know it changed.
  // The wake-word switch in particular did nothing until a reload, which to
  // the person holding the phone is a switch that does not work.
  try {
    window.dispatchEvent(new Event('gamira:settings'));
  } catch {
    /* not a browser */
  }
}

export function updateSettings(patch) {
  const next = { ...getSettings(), ...patch };
  saveSettings(next);
  return next;
}

const sizeMap = { Small: '15px', Standard: '16px', Large: '18px', 'Extra Large': '21px' };

export function applyAccessibility() {
  try {
    const { accessibility } = getSettings();
    const root = document.documentElement;
    root.style.fontSize = sizeMap[accessibility?.textSize] || '16px';
    root.classList.toggle('high-contrast', !!accessibility?.highContrast);
    root.classList.toggle('reduce-motion', !!accessibility?.reduceMotion);
  } catch {
    /* ignore */
  }
}
