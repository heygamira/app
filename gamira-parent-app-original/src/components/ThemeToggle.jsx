import { useState } from 'react';
import { Sun, Moon } from 'lucide-react';
import { getStoredTheme, setTheme, resolveTheme } from '@/lib/theme';

export default function ThemeToggle({ className = '' }) {
  const [theme, setThemeState] = useState(getStoredTheme());
  const resolved = resolveTheme(theme);

  const toggle = () => {
    const next = resolved === 'dark' ? 'light' : 'dark';
    setTheme(next);
    setThemeState(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={resolved === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className={`flex h-11 w-11 items-center justify-center rounded-full border border-border bg-card text-foreground transition-transform active:scale-95 ${className}`}
    >
      {resolved === 'dark' ? (
        <Sun className="h-5 w-5" strokeWidth={2} />
      ) : (
        <Moon className="h-5 w-5" strokeWidth={2} />
      )}
    </button>
  );
}
