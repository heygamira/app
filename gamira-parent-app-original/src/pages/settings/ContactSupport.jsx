import { Mail } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { useT } from '@/lib/i18n';

export default function ContactSupport() {
  const t = useT();
  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('contactSupport')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <div className="flex flex-col items-center py-6 text-center">
          <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary/10">
            <Mail className="h-10 w-10 text-primary" />
          </div>
          <p className="mt-4 text-lg text-muted-foreground">{t('contactSupportDesc')}</p>
        </div>
        <a
          href="mailto:support@gamira.app"
          className="flex items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-4 text-lg font-semibold text-white"
        >
          <Mail className="h-5 w-5" /> support@gamira.app
        </a>
      </main>
    </div>
  );
}
