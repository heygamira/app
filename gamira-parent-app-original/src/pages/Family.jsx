import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, MessageCircle, Phone, Users } from 'lucide-react';
import GamiraAvatar from '@/components/gamira/GamiraAvatar';
import GamiraCard from '@/components/gamira/GamiraCard';
import GamiraSectionHeader from '@/components/gamira/GamiraSectionHeader';
import { useT } from '@/lib/i18n';
import { useAuth } from '@/lib/AuthContext';
import { useSeniorCare } from '@/lib/useSeniorCare';
import { families as familiesApi } from '@/api/gamiraClient';

const ROLE_WORDS = {
  owner: 'Manages your Gamira',
  caregiver: 'Caregiver',
  family: 'Family',
  doctor: 'Doctor',
  viewer: 'Can see your care',
};

export default function Family() {
  const t = useT();
  const { families, user } = useAuth();
  const { contacts, loading, error, seniorId } = useSeniorCare({ contacts: true });

  const [members, setMembers] = useState([]);
  const [membersError, setMembersError] = useState(null);

  const familyId = families[0]?.id;

  const loadMembers = useCallback(async () => {
    if (!familyId) return;
    try {
      setMembers(await familiesApi.members(familyId));
      setMembersError(null);
    } catch (e) {
      setMembersError(e.message);
    }
  }, [familyId]);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  const others = members.filter((member) => member.user_id !== user?.id);
  const shownError = error || membersError;

  return (
    <>
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-background/90 px-5 pt-5 pb-3 backdrop-blur">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{t('familyTitle')}</h1>
      </header>

      <div className="flex flex-col gap-6 px-5 py-5">
        <p className="text-[15px] text-muted-foreground">{t('familySubtitle')}</p>

        {shownError && (
          <div className="flex items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 p-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <p className="text-[15px] leading-snug text-foreground">{shownError}</p>
          </div>
        )}

        {/* Contacts first: this is the section someone opens because they want
            to reach a person, and it is the only one with a phone number. */}
        <div className="flex flex-col gap-3">
          <GamiraSectionHeader title="People you can call" />
          {loading ? (
            <div className="h-20 animate-pulse rounded-2xl border border-border bg-card" />
          ) : contacts.length === 0 ? (
            <GamiraCard>
              <p className="text-[15px] text-muted-foreground">
                {seniorId
                  ? 'No one has been added to call yet. Your family can add contacts in the Gamira dashboard.'
                  : 'Ask your family to add you in the Gamira dashboard.'}
              </p>
            </GamiraCard>
          ) : (
            contacts.map((contact) => (
              <GamiraCard key={contact.id} className="flex items-center gap-3">
                <GamiraAvatar name={contact.name} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-[15px] font-semibold text-foreground">{contact.name}</p>
                    {contact.is_primary && (
                      <span className="shrink-0 rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-semibold text-destructive">
                        {t('primary')}
                      </span>
                    )}
                  </div>
                  <p className="truncate text-[13px] text-muted-foreground">
                    {contact.relationship_label || t('other')} · {contact.phone}
                  </p>
                </div>
                <div className="flex gap-2">
                  <a
                    href={`tel:${contact.phone}`}
                    aria-label={`${t('call')} ${contact.name}`}
                    className="flex h-12 w-12 items-center justify-center rounded-full bg-success/15 text-success transition active:scale-90"
                  >
                    <Phone className="h-5 w-5" />
                  </a>
                  <a
                    href={`sms:${contact.phone}`}
                    aria-label={`Message ${contact.name}`}
                    className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary transition active:scale-90"
                  >
                    <MessageCircle className="h-5 w-5" />
                  </a>
                </div>
              </GamiraCard>
            ))
          )}
        </div>

        <div className="flex flex-col gap-3">
          <GamiraSectionHeader title="People who can see your Gamira" />
          {others.length === 0 ? (
            <GamiraCard className="flex flex-col items-center gap-3 py-8 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/10">
                <Users className="h-7 w-7 text-accent" />
              </div>
              <p className="text-[15px] text-muted-foreground">{t('noFamilyYet')}</p>
            </GamiraCard>
          ) : (
            others.map((member) => (
              <GamiraCard key={member.id} className="flex items-center gap-3">
                <GamiraAvatar name={member.display_name || member.email || '?'} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] font-semibold text-foreground">
                    {member.display_name || member.email || 'Family member'}
                  </p>
                  <p className="truncate text-[13px] text-muted-foreground">
                    {ROLE_WORDS[member.role] || member.role}
                  </p>
                </div>
              </GamiraCard>
            ))
          )}
        </div>

        {/* The old version of this screen let the phone add a "family member"
            that was saved only on this device — nobody else ever saw it, and it
            granted nothing. Membership is decided by the backend. */}
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Your family manages this list in the Gamira dashboard. Anyone here can
          see your medicines and health readings.
        </p>
      </div>
    </>
  );
}
