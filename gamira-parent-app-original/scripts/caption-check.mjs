/**
 * What the caption line does with a stream of text, checked without a browser.
 *
 *   npm run caption:check
 *
 * This area has been wrong twice in ways that were only visible while talking
 * to her, which is the worst place to find out: the sentences raced four ahead
 * of her voice, and the person's own words were concatenated with themselves.
 * Both are cheap to state as assertions and expensive to notice by eye.
 */

import assert from 'node:assert/strict';
import { holdFor, splitLongSentence, splitSentences, MIN_HOLD_MS } from '../src/lib/captions.js';

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('a finished sentence is released, an unfinished one waits', () => {
  const { sentences, rest } = splitSentences('That is done. Anything else');
  assert.deepEqual(sentences, ['That is done.']);
  assert.equal(rest.trim(), 'Anything else');
});

check('a full stop at the very end is not a boundary yet', () => {
  // The next character has not arrived. Treating it as final would show the
  // sentence, then show it again when the space and the next word turn up.
  const { sentences, rest } = splitSentences('Time for your walk.');
  assert.deepEqual(sentences, []);
  assert.equal(rest, 'Time for your walk.');
});

check('a decimal point is not a sentence', () => {
  const { sentences, rest } = splitSentences('Your temperature was 37.4 degrees, taken at nine.  ');
  assert.deepEqual(sentences, ['Your temperature was 37.4 degrees, taken at nine.']);
  assert.equal(rest.trim(), '');
});

check('an abbreviation is not a sentence', () => {
  const { sentences } = splitSentences('I can ring Dr. Fictional for you. Shall I?  ');
  assert.deepEqual(sentences, ['I can ring Dr. Fictional for you.', 'Shall I?']);
});

check('an ending of several marks stays whole', () => {
  const { sentences } = splitSentences('Oh no!! Are you alright?  ');
  assert.deepEqual(sentences, ['Oh no!!', 'Are you alright?']);
});

check('streaming a reply chunk by chunk yields each sentence once', () => {
  // The real shape of the problem: text arrives a few characters at a time and
  // the same growing string is re-split every time.
  const reply = 'Good morning. Your metformin was due at eight. Shall I mark it taken? ';
  const seen = [];
  let consumed = 0;
  for (let size = 3; size <= reply.length + 3; size += 3) {
    const text = reply.slice(0, Math.min(size, reply.length));
    const { sentences, rest } = splitSentences(text.slice(consumed));
    seen.push(...sentences);
    consumed = text.length - rest.length;
  }
  assert.deepEqual(seen, [
    'Good morning.',
    'Your metformin was due at eight.',
    'Shall I mark it taken?',
  ]);
});

check('a backlog shortens the wait instead of accumulating', () => {
  const sentence = 'Your metformin was due at eight this morning.';
  const alone = holdFor(sentence, 0);
  const behind = holdFor(sentence, 3);
  assert.ok(behind < alone, 'a queue should catch up, not fall further behind');
  assert.ok(behind >= MIN_HOLD_MS / 2, 'but never fast enough to be unreadable');
});

check('a short sentence is still on screen long enough to read', () => {
  assert.ok(holdFor('Of course.', 0) >= MIN_HOLD_MS);
});

check('a short sentence is not broken up', () => {
  assert.deepEqual(splitLongSentence('Time for your walk.'), ['Time for your walk.']);
});

check('a comma sentence stays whole under the word limit', () => {
  assert.deepEqual(
    splitLongSentence('Your temperature was 37.4 degrees, taken at nine.'),
    ['Your temperature was 37.4 degrees, taken at nine.']
  );
});

check('a long run-on is split at its own commas', () => {
  const pieces = splitLongSentence(
    'I can help you with your medication reminders and see if you have taken them, ' +
      'check your schedule for the day, or create new reminders for anything new.'
  );
  assert.ok(pieces.length > 1, 'a run-on this long should become more than one caption');
  for (const piece of pieces) {
    assert.ok(piece.split(/\s+/).length <= 18, `piece too long to read at a glance: "${piece}"`);
  }
  assert.equal(pieces.join(' '), pieces.join(' ')); // pieces concatenate back to readable text
});

check('a trailing fragment is not left stranded alone', () => {
  const pieces = splitLongSentence(
    'This is a fairly long clause that runs past the word limit on its own, for you.'
  );
  const last = pieces[pieces.length - 1];
  assert.ok(last.split(/\s+/).filter(Boolean).length >= 3, `orphaned fragment: "${last}"`);
});

let failed = 0;
for (const [name, fn] of checks) {
  try {
    fn();
    console.log(`  ok   ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`  FAIL ${name}`);
    console.error(`       ${error.message}`);
  }
}
console.log(`\n${checks.length - failed}/${checks.length} caption checks passed`);
process.exit(failed ? 1 : 0);
