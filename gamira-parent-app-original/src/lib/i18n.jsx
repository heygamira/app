import { createContext, useContext, useState, useCallback, useMemo, useEffect } from 'react';
import translations from '@/lib/translations';
import { getSettings, updateSettings } from '@/lib/userSettings';

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => getSettings().language || 'English');

  // keep in sync if settings change elsewhere (e.g. Language page saves)
  useEffect(() => {
    const onStorage = () => setLang(getSettings().language || 'English');
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // reflect the active language on the document element
  useEffect(() => {
    document.documentElement.lang = langCode[lang] || 'en';
  }, [lang]);

  const dictionary = translations[lang] || translations.English;

  const t = useCallback(
    (key, ...args) => {
      const val = dictionary[key];
      if (val === undefined) {
        const en = translations.English[key];
        if (en !== undefined) return typeof en === 'function' ? en(...args) : en;
        return key;
      }
      if (typeof val === 'function') return val(...args);
      return val;
    },
    [dictionary]
  );

  const changeLanguage = useCallback((next) => {
    setLang(next);
    updateSettings({ language: next });
  }, []);

  const value = useMemo(() => ({ lang, t, changeLanguage, native: dictionary._native || lang }), [lang, t, changeLanguage, dictionary]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    // fallback so pages work even if provider missing
    const dict = translations.English;
    const t = (key, ...args) => {
      const val = dict[key];
      if (val === undefined) return key;
      return typeof val === 'function' ? val(...args) : val;
    };
    return { lang: 'English', t, changeLanguage: () => {}, native: 'English' };
  }
  return ctx;
}

export function useT() {
  return useI18n().t;
}

export const supportedLanguages = Object.keys(translations).map((name) => ({
  name,
  native: translations[name]._native || name,
}));

export function nativeName(name) {
  return translations[name]?._native || name;
}

export const langCode = {
  English: 'en-US',
  Hindi: 'hi-IN',
  Tamil: 'ta-IN',
  Telugu: 'te-IN',
  Marathi: 'mr-IN',
  Bengali: 'bn-IN',
  Spanish: 'es-ES',
  French: 'fr-FR',
  Chinese: 'zh-CN',
};
