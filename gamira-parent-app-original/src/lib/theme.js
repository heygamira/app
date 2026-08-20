import { Capacitor } from '@capacitor/core';
import { StatusBar, Style } from '@capacitor/status-bar';

const STORAGE_KEY = 'gamira-theme';

export function getStoredTheme() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'dark' || v === 'light' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function resolveTheme(theme) {
  if (theme === 'system') {
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return theme;
}

export function applyTheme(theme) {
  const actual = resolveTheme(theme);
  const root = document.documentElement;
  root.classList.toggle('dark', actual === 'dark');
  syncStatusBar(actual);
}

// Resolves the CSS custom property that already defines this theme's
// background (src/index.css) instead of hand-transcribing its HSL value to
// hex, so the status bar can never drift out of sync with the real token.
function backgroundHex(actual) {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:fixed;top:-9999px;left:-9999px;background-color:hsl(var(--background));';
  document.body.appendChild(probe);
  const rgb = getComputedStyle(probe).backgroundColor;
  document.body.removeChild(probe);
  const match = rgb.match(/(\d+),\s*(\d+),\s*(\d+)/);
  if (!match) return actual === 'dark' ? '#0A1220' : '#F7F9FC';
  const [, r, g, b] = match;
  const toHex = (n) => Number(n).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

function syncStatusBar(actual) {
  if (!(Capacitor.isNativePlatform() && Capacitor.getPlatform() === 'android')) return;
  // Style.Dark = light icons (for a dark background); Style.Light = dark
  // icons (for a light background) — named for the icon color, not the bar.
  StatusBar.setStyle({ style: actual === 'dark' ? Style.Dark : Style.Light }).catch(() => {});
  StatusBar.setBackgroundColor({ color: backgroundHex(actual) }).catch(() => {});
}

export function setTheme(theme) {
  applyTheme(theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* ignore */
  }
}
