import { AlertCircle, MapPin, Phone, ShieldAlert } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { useT } from '@/lib/i18n';
import { useSeniorCare } from '@/lib/useSeniorCare';

function ContactCard({ contact, isPrimary = false, primaryLabel = '' }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-card p-4">
      <a
        href={`tel:${contact.phone}`}
        aria-label={`Call ${contact.name}`}
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ${
          isPrimary ? 'bg-destructive/15 text-destructive' : 'bg-primary/10 text-primary'
        }`}
      >
        <Phone className="h-6 w-6" strokeWidth={2} />
      </a>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-lg font-semibold text-foreground">{contact.name}</p>
          {isPrimary && (
            <span className="shrink-0 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive">
              {primaryLabel}
            </span>
          )}
        </div>
        <p className="truncate text-sm text-muted-foreground">
          {[contact.relationship_label, contact.phone].filter(Boolean).join(' · ')}
        </p>
      </div>
    </div>
  );
}

/**
 * Emergency contacts.
 *
 * These used to live in this phone's localStorage, so the family who set up the
 * account could not see them and the dashboard's list was a different list. They
 * come from the backend now. The screen is read-only here on purpose: adding a
 * contact needs a write role, which the cared-for person does not hold.
 */
export default function Emergency() {
  const t = useT();
  const { contacts, loading, error, seniorId } = useSeniorCare({ contacts: true });

  const primary = contacts.find((contact) => contact.is_primary) || contacts[0] || null;
  const others = contacts.filter((contact) => contact !== primary);

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title={t('emergencyTitle')} />

      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <div className="mb-6 flex items-start gap-3 rounded-2xl border border-destructive/30 bg-destructive/10 p-4">
          <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-destructive" />
          <p className="text-base text-foreground">
            Pressing SOS calls the contact below from this phone. Gamira does not
            contact emergency services and cannot alert anyone on its own — in an
            emergency, call your local emergency number.
          </p>
        </div>

        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <p className="text-base leading-snug text-foreground">{error}</p>
          </div>
        )}

        <h2 className="mb-3 text-lg font-bold text-foreground">{t('sosEmergencyContact')}</h2>

        {loading ? (
          <div className="h-20 animate-pulse rounded-2xl border border-border bg-card" />
        ) : !seniorId ? (
          <div className="rounded-2xl border border-border bg-card p-4">
            <p className="text-base text-muted-foreground">
              Ask your family to add you in the Gamira dashboard.
            </p>
          </div>
        ) : primary ? (
          <div className="flex flex-col gap-3">
            <ContactCard contact={primary} isPrimary primaryLabel={t('primary')} />
            <a
              href={`tel:${primary.phone}`}
              className="flex h-14 items-center justify-center gap-2 rounded-2xl bg-destructive text-base font-semibold text-white transition active:scale-95"
            >
              <Phone className="h-5 w-5" /> Call {primary.name}
            </a>
          </div>
        ) : (
          <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-4">
            <p className="text-base text-muted-foreground">{t('noContactSet')}</p>
            <p className="text-sm text-muted-foreground">
              Your family adds emergency contacts in the Gamira dashboard.
            </p>
          </div>
        )}

        <h2 className="mb-3 mt-8 text-lg font-bold text-foreground">{t('otherEmergencyContacts')}</h2>
        <div className="flex flex-col gap-3">
          {others.length === 0 ? (
            <p className="text-base text-muted-foreground">{t('noOtherContacts')}</p>
          ) : (
            others.map((contact) => <ContactCard key={contact.id} contact={contact} />)
          )}
        </div>

        <div className="mt-8 flex items-start gap-3 rounded-2xl border border-border bg-card p-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent/10">
            <MapPin className="h-6 w-6 text-accent" strokeWidth={2} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-base font-semibold text-foreground">{t('shareLocation')}</p>
            {/* The old toggle wrote a flag to this phone that nothing ever read.
                A location-sharing switch that shares nothing is worse than none. */}
            <p className="mt-1 text-sm text-muted-foreground">
              Not available yet. Gamira cannot send your location to anyone, so
              there is nothing to switch on.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
