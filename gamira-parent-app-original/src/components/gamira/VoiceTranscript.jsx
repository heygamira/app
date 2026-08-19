import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { holdFor, splitLongSentence, splitSentences } from '@/lib/captions';

/**
 * One line under the microphone: the sentence being spoken right now.
 *
 * Not a chat history, and not a whole turn either. A list of bubbles turns a
 * conversation into a document and pushes the day off the bottom of the screen;
 * a whole turn does the same thing more slowly, because a four-line reply moves
 * everything below it — including the Taken button, which is a tap target that
 * must not wander mid-conversation.
 *
 * So: one sentence at a time, in a slot of fixed height. Nothing on the page
 * moves, whoever is talking and however much they say.
 *
 * ## Why the sentences used to race ahead of her
 *
 * This is the part that was actually broken, and it is not a timing tweak. The
 * transcript is *generated text*, and it arrives as fast as the model can
 * produce it — the whole reply is usually complete a second or two before she
 * has finished saying the first sentence of it out loud. Showing each sentence
 * as it arrived therefore showed the fourth while she was still speaking the
 * first. The text was never late; it was far too early.
 *
 * Nothing can be inferred from arrival time, so arrival time is not used.
 * Sentences go into a queue and are released at *speaking* pace — `MS_PER_WORD`,
 * between a floor and a ceiling. That is a guess, but a guess at how long a
 * sentence takes to say is a good one, and it gets the only thing that matters
 * right: what is on the screen is roughly what is in the room.
 *
 * If the queue falls behind — a long reply, or she is speaking faster than the
 * estimate — the hold shortens in proportion, so it catches up rather than
 * drifting further behind for the rest of the turn.
 *
 * The same problem shows up one level down: `splitSentences` only knows where
 * a sentence *ends*, so a long run-on with no full stop yet — several clauses
 * on commas — arrives as one "sentence" that can take her several seconds to
 * say. Held as a single caption it either sits there through the silence after
 * she's finished, or hits `MAX_HOLD_MS` and vanishes mid-clause.
 * `splitLongSentence` (in `lib/captions`) breaks anything over
 * `MAX_CLAUSE_WORDS` at its own commas and semicolons before it is queued, so
 * a run-on reads — and paces — as the several clauses it actually is.
 *
 * ## Whose words these are
 *
 * Colour, not labels. Theirs in the ordinary muted grey; hers in the
 * blue-to-violet of the microphone's own gradient — the same 135° angle as the
 * mic button itself, not a flat left-to-right wash — which is the one piece of
 * colour in this app that already means "Gamira". Flat white was anonymous and
 * flat violet was a wall of one colour; the gradient reads as hers at a glance,
 * and works in both themes because both ends are saturated.
 *
 * ## How long their own words stay
 *
 * Long enough to read, and no longer. `THEIR_DWELL_MS` is what her first
 * sentence waits out. A second is plenty when she is answering immediately —
 * it was nearly a second and a half, so their sentence sat there through the
 * start of her reply.
 */

// What their own sentence is guaranteed before hers can take the slot.
const THEIR_DWELL_MS = 1000;
// Nothing said for this long, with nothing queued: the slot empties. A last
// sentence left on screen for the rest of the afternoon is not a transcript.
const LINGER_MS = 5000;
// A trailing fragment with no full stop yet is only shown once the words have
// stopped arriving; otherwise it flickers a word at a time.
const SETTLE_MS = 600;

export default function VoiceTranscript({ turns = [], thinking = false }) {
  const [shown, setShown] = useState(null);

  // Everything below is deliberately outside React state: it changes several
  // times a second while she is speaking, and none of it is worth a render.
  const queueRef = useRef([]);
  const readingRef = useRef({ at: 0, consumed: 0 });
  const untilRef = useRef(0);
  const tickRef = useRef(null);

  useEffect(() => {
    const latest = [...turns].reverse().find((turn) => turn.text?.trim()) || null;

    const pump = () => {
      tickRef.current = null;
      const now = Date.now();
      if (now < untilRef.current) {
        tickRef.current = setTimeout(pump, untilRef.current - now);
        return;
      }
      const next = queueRef.current.shift();
      if (next) {
        untilRef.current = now + holdFor(next.text, queueRef.current.length);
        setShown(next);
        tickRef.current = setTimeout(pump, untilRef.current - now);
        return;
      }
      // Drained. Come back after a pause and clear the slot if nothing new has
      // arrived by then.
      tickRef.current = setTimeout(() => {
        tickRef.current = null;
        if (!queueRef.current.length) setShown(null);
      }, LINGER_MS);
    };

    const enqueue = (text) => {
      const line = text.trim();
      if (!line) return;
      // A long, comma-heavy sentence is several clauses of speech, not one —
      // break it up so what's on screen tracks which clause she's on rather
      // than showing the whole run-on until it times out or vanishes early.
      for (const piece of splitLongSentence(line)) {
        queueRef.current.push({
          role: 'gamira',
          text: piece,
          id: `gamira:${readingRef.current.at}:${queueRef.current.length}:${piece.slice(0, 24)}`,
        });
      }
      if (!tickRef.current) pump();
    };

    if (!latest) {
      queueRef.current = [];
      readingRef.current = { at: 0, consumed: 0 };
      untilRef.current = 0;
      if (tickRef.current) clearTimeout(tickRef.current);
      tickRef.current = null;
      setShown(null);
      return undefined;
    }

    if (readingRef.current.at !== latest.at) {
      // A new turn. If it is theirs, anything of hers still queued has been
      // overtaken by events: they are talking now, and captions for a reply
      // they interrupted are not what to show them.
      if (latest.role === 'them') {
        queueRef.current = [];
        untilRef.current = 0;
      }
      readingRef.current = { at: latest.at, consumed: 0 };
    }

    const text = latest.text || '';

    if (latest.role === 'them') {
      // Their words are live — the interim transcript is what they are saying
      // as they say it — so there is nothing to pace against and nothing to
      // wait for. It replaces whatever is up.
      const line = text.trim();
      readingRef.current.consumed = text.length;
      if (line) {
        queueRef.current = [];
        untilRef.current = Date.now() + THEIR_DWELL_MS;
        setShown({ role: 'them', text: line, id: `them:${latest.at}` });
        if (tickRef.current) clearTimeout(tickRef.current);
        tickRef.current = setTimeout(pump, THEIR_DWELL_MS);
      }
      return undefined;
    }

    // If the turn text were ever truncated at the front, this offset would
    // point at the wrong place. `appendTurn` keeps 4000 characters for exactly
    // that reason; this is the belt to its braces, and it skips rather than
    // stalls, because a missed sentence is better than a caption line that
    // silently stops for the rest of the turn.
    if (readingRef.current.consumed > text.length) {
      readingRef.current.consumed = text.length;
    }
    const fresh = text.slice(readingRef.current.consumed);
    const { sentences, rest } = splitSentences(fresh);
    for (const sentence of sentences) enqueue(sentence);
    readingRef.current.consumed = text.length - rest.length;

    if (!rest.trim()) return undefined;
    // A fragment with no ending yet. Wait to see whether more of it arrives; a
    // turn that simply stopped without a full stop is still the last thing she
    // said, and should be shown.
    const settled = setTimeout(() => {
      if (readingRef.current.at !== latest.at) return;
      if (readingRef.current.consumed >= text.length) return;
      readingRef.current.consumed = text.length;
      enqueue(rest);
    }, SETTLE_MS);
    return () => clearTimeout(settled);
  }, [turns]);

  // Never leave a timer running behind a navigation.
  useEffect(
    () => () => {
      if (tickRef.current) clearTimeout(tickRef.current);
      tickRef.current = null;
    },
    []
  );

  return (
    // A fixed height, not a minimum: this is the whole reason nothing below
    // moves. Three lines at 16px is what one spoken sentence needs.
    <div className="flex h-[5.25rem] w-full items-start justify-center overflow-hidden px-2">
      <AnimatePresence mode="wait" initial={false}>
        {shown ? (
          <motion.p
            key={shown.id}
            initial={{ opacity: 0, y: 6, filter: 'blur(2px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -6, filter: 'blur(2px)' }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            aria-live="polite"
            className={
              shown.role === 'them'
                ? 'max-w-[20rem] text-center text-[16px] font-normal leading-snug text-muted-foreground'
                : 'max-w-[20rem] bg-gradient-to-br from-primary to-accent bg-clip-text text-center text-[16px] font-semibold leading-snug text-transparent'
            }
          >
            {shown.text}
          </motion.p>
        ) : thinking ? (
          <motion.div
            key="thinking"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pt-5"
          >
            <Thinking />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** She is about to answer. Three dots, and nothing that claims to be words. */
function Thinking() {
  return (
    <div className="flex items-center gap-1.5" aria-hidden="true">
      {[0, 1, 2].map((dot) => (
        <motion.span
          key={dot}
          className="h-1.5 w-1.5 rounded-full bg-accent/60"
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: dot * 0.18 }}
        />
      ))}
    </div>
  );
}
