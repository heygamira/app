import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import ThemeToggle from '@/components/ThemeToggle';
import { useT } from '@/lib/i18n';

export default function SettingsHeader({ title, onBack = null }) {
  const navigate = useNavigate();
  const t = useT();
  const handleBack = () => (onBack ? onBack() : navigate('/settings'));

  return (
    <header className="flex items-center justify-between px-5 pt-4 pb-3">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={handleBack}
          aria-label={t('back')}
          className="flex h-11 w-11 items-center justify-center rounded-full text-foreground active:bg-muted"
        >
          <ArrowLeft className="h-6 w-6" strokeWidth={2} />
        </button>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
      </div>
      <ThemeToggle />
    </header>
  );
}
