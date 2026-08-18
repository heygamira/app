import { useCallback, useEffect, useState } from 'react';
import { Loader2, Users } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { ai as aiApi } from '@/api/gamiraClient';
import { useSeniorCare } from '@/lib/useSeniorCare';

/**
 * What Gamira has told this person's family about them.
 *
 * The persona promises: *"You are not there to report on them; if something
 * genuinely needs a family member, say so to them first, openly."* She does say
 * it first — the backend refuses to send anything she did not mention out loud
 * — but openly has to survive the conversation ending. Somebody should be able
 * to check what was said about them without asking anybody.
 *
 * Shows the message itself, word for word, not a paraphrase of it. Anything
 * softer would be a summary of a summary, and the whole point is that this is
 * the text their family actually received.
 */
export default function FamilyNotices() {
  const { seniorId } = useSeniorCare({});
  const [notices, setNotices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!seniorId) {
      setLoading(false);
      return;
    }
    try {
      setNotices(await aiApi.listFamilyNotices(seniorId));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [seniorId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title="What your family was told" />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-5 text-base leading-relaxed text-muted-foreground">
          Gamira only tells your family something after she has said so to you
          first. This is everything she has sent, exactly as they received it.
        </p>

        {loading && (
          <div className="flex items-center gap-2 text-base text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading…
          </div>
        )}

        {!loading && error && (
          <p className="rounded-2xl border border-border bg-card p-4 text-base text-muted-foreground">
            That did not load just now. Please try again in a moment.
          </p>
        )}

        {!loading && !error && notices.length === 0 && (
          <div className="rounded-2xl border border-border bg-card p-6 text-center">
            <Users className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <p className="text-base text-muted-foreground">
              Nothing has been sent to your family.
            </p>
          </div>
        )}

        <ul className="flex flex-col gap-3">
          {notices.map((notice) => (
            <li key={notice.id} className="rounded-2xl border border-border bg-card p-4">
              <p className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
                {new Date(notice.created_at).toLocaleDateString(undefined, {
                  weekday: 'long',
                  day: 'numeric',
                  month: 'long',
                })}
              </p>
              <p className="mt-1 text-[17px] font-semibold leading-snug text-foreground">
                {notice.title}
              </p>
              <p className="mt-1 text-[16px] leading-snug text-muted-foreground">
                {notice.body}
              </p>
              <p className="mt-2 text-[14px] text-muted-foreground">
                Sent to {notice.recipients}{' '}
                {notice.recipients === 1 ? 'person' : 'people'} in your family.
              </p>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
