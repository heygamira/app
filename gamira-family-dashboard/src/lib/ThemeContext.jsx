import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

const STORAGE_KEY = 'gamira_theme';

/**
 * @typedef {{
 *   theme: 'light' | 'dark',
 *   setTheme: (theme: 'light' | 'dark') => void,
 *   toggle: () => void,
 *   isDark: boolean,
 * }} ThemeContextValue
 */

/** @type {React.Context<ThemeContextValue>} */
const ThemeContext = createContext({
  theme: 'light',
  setTheme: () => {},
  toggle: () => {},
  isDark: false,
});

/** @returns {'light' | 'dark'} */
function readInitialTheme() {
  if (typeof window === 'undefined') return 'light';
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // storage blocked — fall through to the system preference
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readInitialTheme);

  // Tailwind is configured with darkMode: ["class"], so the class on <html> is
  // what actually swaps the palette in index.css.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    root.style.colorScheme = theme;
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  }, []);

  const value = useMemo(
    () => ({ theme, setTheme, toggle, isDark: theme === 'dark' }),
    [theme, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

export default ThemeContext;
