import SettingsHeader from '@/components/SettingsHeader';
import Toggle from '@/components/Toggle';
import { useT } from '@/lib/i18n';
import { usePushRegistration } from '@/lib/usePushRegistration';

export default function Notifications() {
  const t = useT();
  const { supported, permission, status, error, enable } = usePushRegistration();

  const checked = permission === 'granted' && status === 'registered';

  // There is no in-app "turn off": a browser never lets a page revoke a
  // permission it holds, only grant one. Pretending a tap here could undo it
  // would be the dark pattern this app's own guidance warns against — the
  // hint below the toggle says where that decision actually lives instead.
  const handleChange = (next) => {
    if (next) enable();
  };

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('notificationsTitle')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-6 text-base text-muted-foreground">{t('notificationsSubtitle')}</p>

        {!supported && (
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-base text-foreground">{t('notificationsUnsupported')}</p>
          </div>
        )}

        {supported && permission === 'denied' && (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4">
            <p className="text-lg font-semibold text-foreground">{t('notificationsBlockedTitle')}</p>
            <p className="mt-1 text-base text-muted-foreground">{t('notificationsBlockedDesc')}</p>
          </div>
        )}

        {supported && permission !== 'denied' && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between rounded-2xl border border-border bg-card p-4">
              <div className="flex-1 pr-3">
                <p className="text-lg font-semibold text-foreground">{t('pushNotifications')}</p>
                <p className="text-sm text-muted-foreground">{t('notificationsToggleDesc')}</p>
              </div>
              <Toggle checked={checked} onChange={handleChange} ariaLabel={t('pushNotifications')} />
            </div>

            {status === 'registering' && (
              <p className="text-sm text-muted-foreground">{t('notificationsEnabling')}</p>
            )}
            {status === 'error' && (
              <p className="text-sm text-destructive">{error || t('notificationsError')}</p>
            )}
            {checked && (
              <p className="text-sm text-muted-foreground">{t('notificationsToggleHint')}</p>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
