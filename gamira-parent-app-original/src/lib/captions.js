/**
 * Turning a stream of generated text into captions somebody can read.
 *
 * Split out of the component because it is the part that was wrong twice and
 * the part that can be checked without a browser: `npm run caption:check`.
 *
 * The problem it exists for: the transcript is generated text and arrives as
 * fast as the model can produce it, so a four-sentence reply is complete a
 * second or two before Gamira has finished saying the first sentence of it out
 * loud. Anything that shows a sentence when it *arrives* shows the fourth while
 * she is speaking the first. Arrival time carries no information about speech,
 * so none of it is used: sentences are released at a speaking pace instead.
 */

// Roughly 2.6 words a second, which is unhurried speech — she is told to speak
// calmly, and this is her voice, not a newsreader's.
export const MS_PER_WORD = 380;
export const MIN_HOLD_MS = 1100;
export const MAX_HOLD_MS = 6000;

const ENDINGS = '.!?…';

/**
 * Words whose full stop is part of the word.
 *
 * Only titles and the two Latin ones, because those are what turn up in this
 * app: she offers to ring Dr. Fictional, and splitting there put "I can ring
 * Dr." on the screen on its own — which is a caption that says something
 * different from what she said. Case-insensitive, dot stripped before the
 * comparison.
 */
const ABBREVIATIONS = new Set([
  'dr', 'mr', 'mrs', 'ms', 'prof', 'st', 'sr', 'jr', 'mt', 'no', 'vs',
  'e.g', 'i.e', 'etc', 'approx',
]);

function endsAnAbbreviation(text, dot) {
  if (text[dot] !== '.') return false;
  let start = dot;
  while (start > 0 && !/\s/.test(text[start - 1])) start -= 1;
  const word = text.slice(start, dot).toLowerCase();
  return ABBREVIATIONS.has(word);
}

/**
 * Split into whole sentences, plus whatever is left over.
 *
 * Two rules, both of them about not cutting in the wrong place:
 *
 * - a boundary needs whitespace after it, so "one twenty over eighty." is not
 *   split at the decimal point of a number — and a full stop that belongs to
 *   an abbreviation is not one either, or "I can ring Dr. Fictional for you"
 *   becomes a caption reading "I can ring Dr.";
 * - a boundary at the very end of the text is *not* a boundary yet, because
 *   the next character has not arrived. It stays in `rest` until either more
 *   text turns up or the caller decides the words have stopped.
 *
 * @param {string} text
 * @returns {{sentences: string[], rest: string}}
 */
export function splitSentences(text) {
  const sentences = [];
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (!ENDINGS.includes(text[i])) continue;
    // Run past "?!" and "..." so a sentence is not cut inside its own ending.
    let end = i;
    while (end + 1 < text.length && ENDINGS.includes(text[end + 1])) end += 1;
    const after = text[end + 1];
    if (after === undefined) break;
    if (!/\s/.test(after)) {
      i = end;
      continue;
    }
    if (end === i && endsAnAbbreviation(text, i)) {
      continue;
    }
    const sentence = text.slice(start, end + 1).trim();
    if (sentence) sentences.push(sentence);
    start = end + 1;
    i = end;
  }
  return { sentences, rest: text.slice(start) };
}

// Above this many words, one sentence is still too much for one caption.
const MAX_CLAUSE_WORDS = 12;

function wordCount(text) {
  return text.split(/\s+/).filter(Boolean).length;
}

/**
 * Break one long sentence into caption-sized pieces.
 *
 * `splitSentences` is right to leave "Your temperature was 37.4 degrees,
 * taken at nine." whole — it *is* one sentence. But a reply with no full stop
 * yet can still be a run-on of several clauses, comma after comma, and she is
 * saying it one clause at a time. Holding the whole thing as a single caption
 * means it either sits on screen through a silence after she's finished it, or
 * — capped at `MAX_HOLD_MS` — vanishes while she is still partway through it.
 * Either way the screen and her voice have come apart.
 *
 * So above `MAX_CLAUSE_WORDS`, a sentence is broken at its own commas and
 * semicolons: the places a spoken sentence actually pauses, not an arbitrary
 * cut. A short sentence passes through untouched — this only fires on the
 * run-ons.
 *
 * @param {string} sentence
 * @returns {string[]}
 */
export function splitLongSentence(sentence) {
  const text = sentence.trim();
  if (!text) return [];
  if (wordCount(text) <= MAX_CLAUSE_WORDS) return [text];

  const clauses = text.split(/(?<=[,;])\s+/);
  const pieces = [];
  let current = '';
  for (const clause of clauses) {
    const candidate = current ? `${current} ${clause}` : clause;
    if (current && wordCount(candidate) > MAX_CLAUSE_WORDS) {
      pieces.push(current);
      current = clause;
    } else {
      current = candidate;
    }
  }
  if (current) pieces.push(current);

  // A clause with no comma of its own can still run long — a hard break by
  // word count beats a caption that outlasts the words it stands for.
  const sized = [];
  for (const piece of pieces) {
    if (wordCount(piece) <= MAX_CLAUSE_WORDS * 1.5) {
      sized.push(piece);
      continue;
    }
    const words = piece.split(/\s+/).filter(Boolean);
    for (let i = 0; i < words.length; i += MAX_CLAUSE_WORDS) {
      sized.push(words.slice(i, i + MAX_CLAUSE_WORDS).join(' '));
    }
  }

  // A trailing fragment too short to read on its own belongs with what came
  // before it, not flashed alone for a second.
  if (sized.length > 1 && wordCount(sized[sized.length - 1]) < 3) {
    const last = sized.pop();
    sized[sized.length - 1] = `${sized[sized.length - 1]} ${last}`;
  }

  return sized;
}

/**
 * How long one sentence stays on screen.
 *
 * `queued` is how many are waiting behind it. More than one means the estimate
 * is running slow — a long reply, or she is speaking faster than the average —
 * so the wait is divided rather than left to accumulate for the rest of the
 * turn. Without that, a caption can end up a paragraph behind the voice and
 * never catch up.
 *
 * @param {string} text
 * @param {number} queued
 * @returns {number} milliseconds
 */
export function holdFor(text, queued = 0) {
  const words = text.split(/\s+/).filter(Boolean).length;
  const estimate = Math.min(MAX_HOLD_MS, Math.max(MIN_HOLD_MS, words * MS_PER_WORD));
  return queued > 1 ? Math.max(MIN_HOLD_MS / 2, estimate / queued) : estimate;
}
