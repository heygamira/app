import { useEffect, useState } from 'react';
import { AlertCircle, Check } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import FormField from '@/components/FormField';
import InfoRow from '@/components/InfoRow';
import { useT } from '@/lib/i18n';
import { useAuth } from '@/lib/AuthContext';
import { ageFrom } from '@/api/parentData';

/**
 * My profile.
 *
 * Two different things live here, and the difference matters:
 *
 *  - The account name is this person's own, and they can change it.
 *  - The care record — date of birth, conditions, allergies, timezone — is
 *    maintained by their family and is read-only here. The backend enforces
 *    that; showing an editable form that the server would reject would be a lie
 *    told twice.
 *
 * It used to save everything to this phone's localStorage, where nobody else
 * ever saw it.
 */
export default function Profile() {
  const t = useT();
  const { user, self, updateProfile } = useAuth();

  const [name, setName] = useState('');
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setName(user?.display_name || '');
    setEditing(!user?.display_name);
  }, [user]);

  const save = async () => {
    setSaving(true);
    try {
      await updateProfile({ display_name: name.trim() });
      setEditing(false);
      setSaved(true);
      setError(null);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const initials = (name || self?.preferred_name || 'G').trim().charAt(0).toUpperCase() || 'G';
  const age = ageFrom(self?.date_of_birth);

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('myProfile')} />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <div className="flex flex-col items-center py-4">
          {self?.avatar_url ? (
            <img
              src={self.avatar_url}
              alt={self.preferred_name || ''}
              className="h-24 w-24 rounded-full object-cover"
            />
          ) : (
            <div className="flex h-24 w-24 items-center justify-center rounded-full bg-primary/10 text-4xl font-bold text-primary">
              {initials}
            </div>
          )}
        </div>

        {saved && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-success/30 bg-success/10 p-3 text-success">
            <Check className="h-5 w-5" />
            <span className="text-base font-medium">{t('profileUpdated')}</span>
          </div>
        )}

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <p className="text-base leading-snug text-foreground">{error}</p>
          </div>
        )}

        {editing ? (
          <div className="flex flex-col gap-4">
            <FormField
              label={t('profileName')}
              value={name}
              onChange={setName}
              placeholder={t('yourName')}
            />
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="h-14 w-full rounded-2xl bg-primary text-base font-semibold text-primary-foreground transition active:scale-95 disabled:opacity-50"
            >
              {saving ? '…' : t('saveChanges')}
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <InfoRow label={t('profileName')} value={name || '—'} />
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="mt-2 h-14 w-full rounded-2xl bg-primary text-base font-semibold text-primary-foreground transition active:scale-95"
            >
              {t('editProfile')}
            </button>
          </div>
        )}

        <h2 className="mb-3 mt-8 text-lg font-bold text-foreground">Your care record</h2>
        <div className="flex flex-col gap-3">
          <InfoRow label="Known as" value={self?.preferred_name || '—'} />
          <InfoRow label={t('profileAge')} value={age != null ? String(age) : '—'} />
          <InfoRow label={t('profilePhone')} value={self?.phone || '—'} />
          <InfoRow label="Blood group" value={self?.blood_group || '—'} />
          <InfoRow label="Conditions" value={(self?.conditions || []).join(', ') || '—'} />
          <InfoRow label="Allergies" value={(self?.allergies || []).join(', ') || '—'} />
          <InfoRow label="Timezone" value={self?.timezone || '—'} />
        </div>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Your family keeps these details up to date in the Gamira dashboard. Ask
          them to change anything that is wrong.
        </p>
      </main>
    </div>
  );
}
