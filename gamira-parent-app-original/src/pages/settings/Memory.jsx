import { useCallback, useEffect, useState } from 'react';
import { Brain, Loader2, Trash2 } from 'lucide-react';
import SettingsHeader from '@/components/SettingsHeader';
import { ai as aiApi } from '@/api/gamiraClient';
import { useSeniorCare } from '@/lib/useSeniorCare';

/**
 * What Gamira remembers about the person using this phone.
 *
 * This screen is the condition on which the memory feature is reasonable at
 * all. A companion that keeps private notes about somebody, which that person
 * cannot read and cannot remove, is a different and worse product than one
 * that remembers their granddaughter's name — and the only difference between
 * the two is this list.
 *
 * So: plain sentences, at the app's normal size, in the order they were
 * written, each with a Forget button that is a real button and not an icon in
 * a menu. No provenance detail here — the family dashboard shows which
 * conversation a memory came from, and this screen is for the person, who does
 * not need to know what a prompt version is.
 */

const KIND_WORDS = {
  person: 'Someone in your life',
  preference: 'Something you like',
  routine: 'Part of your day',
  interest: 'Something you enjoy',
  event: 'Something coming up',
  mood: 'How a conversation felt',
  concern: 'Something Gamira noticed',
};

export default function Memory() {
  const { seniorId } = useSeniorCare({});
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [forgetting, setForgetting] = useState(null);

  const load = useCallback(async () => {
    // Signed in but not yet linked to a profile. Nothing to load, and nothing
    // to spin about — the empty state below says it plainly.
    if (!seniorId) {
      setLoading(false);
      return;
    }
    try {
      setMemories(await aiApi.listMemories(seniorId));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [seniorId]);

  useEffect(() => { load(); }, [load]);

  const forget = async (id) => {
    setForgetting(id);
    try {
      await aiApi.forgetMemory(id);
      // Removed here as well as on the server, so the list does not sit there
      // unchanged while a request finishes on a slow connection.
      setMemories((prev) => prev.filter((memory) => memory.id !== id));
    } catch (err) {
      setError(err);
    } finally {
      setForgetting(null);
    }
  };

  return (
    <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-md flex-col bg-background">
      <SettingsHeader title="What Gamira remembers" />
      <main className="flex-1 overflow-y-auto px-5 pb-12 pt-2">
        <p className="mb-5 text-base leading-relaxed text-muted-foreground">
          Gamira keeps a few small things about you so she does not have to ask
          again. You can remove any of them, and she will not write it down
          again.
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

        {!loading && !error && memories.length === 0 && (
          <div className="rounded-2xl border border-border bg-card p-6 text-center">
            <Brain className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <p className="text-base text-muted-foreground">
              Nothing yet. Gamira remembers things as you talk to her.
            </p>
          </div>
        )}

        <ul className="flex flex-col gap-3">
          {memories.map((memory) => (
            <li
              key={memory.id}
              className="rounded-2xl border border-border bg-card p-4"
            >
              <p className="text-[13px] font-medium uppercase tracking-wide text-muted-foreground">
                {KIND_WORDS[memory.kind] || 'Something Gamira noted'}
              </p>
              <p className="mt-1 text-[17px] leading-snug text-foreground">
                {memory.content}
              </p>
              <button
                type="button"
                onClick={() => forget(memory.id)}
                disabled={forgetting === memory.id}
                className="mt-3 flex h-11 items-center gap-2 rounded-xl px-3 text-[15px] font-semibold text-destructive transition active:bg-destructive/10 disabled:opacity-60"
              >
                {forgetting === memory.id ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Trash2 className="h-5 w-5" />
                )}
                Forget this
              </button>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
