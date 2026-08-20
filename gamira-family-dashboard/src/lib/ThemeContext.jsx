import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { StatusBar, Style } from '@capacitor/status-bar';

const STORAGE_KEY = 'gamira_theme';

// Matches --background in index.css for each theme (hsl(210 40% 98%) light,
// hsl(222 47% 7%) dark) — the status bar background should read as part of
// the page, not a separate native chrome color.
const STATUS_BAR_BACKGROUND = { light: '#F8FAFC', dark: '#0B1120' };

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
    if (Capacitor.isNativePlatform()) {
      // Style.Dark = light icons (for a dark background), Style.Light = dark
      // icons (for a light background) — named for the icon color, not the
      // background, so this pairing looks backwards but is correct.
      StatusBar.setStyle({ style: theme === 'dark' ? Style.Dark : Style.Light });
      StatusBar.setBackgroundColor({ color: STATUS_BAR_BACKGROUND[theme] });
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
