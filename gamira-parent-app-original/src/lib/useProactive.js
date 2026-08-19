import { useCallback, useEffect, useRef, useState } from 'react';
import { getSettings } from '@/lib/userSettings';
import { sortableTime } from '@/lib/schedule';

/**
 * Deciding when Gamira should speak first.
 *
 * Everything else in this app waits to be asked. That is the wrong shape for
 * the one case that matters most: a dose that is late is late precisely
 * because nobody looked at the phone. A companion that only ever answers is no
 * use to somebody who has forgotten there is anything to ask about.
 *
 * This hook decides *whether* and *what*; it does not speak. It hands back a
 * nudge carrying a `brief` — a bracketed note built from what is already on
 * screen — and the caller opens a real Live session with it, so the sentence
 * comes out in Gamira's own voice through the same path every other sentence
 * takes.
 *
 * It used to speak here, through the browser's `speechSynthesis`. That was a
 * different voice from the one the person had been talking to five minutes
 * earlier — flat, wrongly paced, and unable to hear a reply — so a nudge was
 * an announcement rather than the start of a conversation. Being able to say
 * "yes, I've taken it" and have that recorded is the whole point.
 *
 * Deliberately small in every other way:
 *
 * - **Once per thing, per day.** Remembered across reloads, because a nudge
 *   that repeats every time a screen mounts is nagging, and the persona
 *   forbids nagging for good reason.
 * - **Not at night.** The same courtesy the backend applies to family notices.
 * - **Never about a medicine's contents.** The brief carries a name and a
 *   time, which is what is already on the screen, and nothing about what to do.
 *
 * Off by default is deliberately *not* the choice here — a reminder that has
 * to be discovered in Settings will not reach the person who needs it — but it
 * is one switch away in Settings › Voice.
 */

// How overdue a daily routine has to be before it is worth saying out loud.
// Medicine and one-off reminders speak up the moment they're due — see
// `VOICE_FOLLOW_SECONDS` below — but a recurring routine keeps a grace period,
// so a nudge does not chase someone who is already up and moving.
const OVERDUE_MINUTES = 20;
// A notification for this dose or reminder has already gone out the moment it
// becomes due — that is the backend's job, not this hook's. Voice follows a
// few seconds later, not at the same instant and not minutes later, so it
// reads as "the phone buzzed, then she mentioned it" rather than the two
// competing for attention or the second one turning up long after the first.
const VOICE_FOLLOW_SECONDS = 6;
// Nothing is volunteered outside these local hours.
const QUIET_END_HOUR = 8;
const QUIET_START_HOUR = 21;
const STORE_KEY = 'gamira.proactive.spoken';

/**
 * Today, where the person is.
 *
 * `toISOString()` gives the **UTC** date, so the once-a-day record rolled over
 * at 05:30 local in India and mid-afternoon in the Americas — wiping the
 * morning's entries, or suppressing an evening dose that shared a UTC day with
 * one already spoken about. The same class of bug was fixed in the backend and
 * was still sitting here.
 */
const today = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);
};

function alreadySaid(key) {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
    return raw.day === today() && Array.isArray(raw.keys) && raw.keys.includes(key);
  } catch {
    return false;
  }
}

function remember(key) {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
    const keys = raw.day === today() && Array.isArray(raw.keys) ? raw.keys : [];
    localStorage.setItem(
      STORE_KEY,
      JSON.stringify({ day: today(), keys: [...keys, key] })
    );
  } catch {
    /* a nudge that cannot be remembered is better than no nudge */
  }
}

/**
 * Minutes since a local HH:MM today, or null if it is still ahead.
 *
 * `timezone` is the reminder's own, which is the authority — this used to
 * compare against the browser's clock, so a device set to the wrong place, or
 * one that had travelled, silently shifted the whole window.
 */
function minutesPast(localTime, now, timezone) {
  const padded = sortableTime(localTime);
  if (padded === '99:99') return null;
  const [hours, minutes] = padded.split(':').map(Number);
  const theirNow = localParts(now, timezone);
  const delta = theirNow.hour * 60 + theirNow.minute - (hours * 60 + minutes);
  return delta >= 0 ? delta : null;
}

/** The hour and minute where this person is, whatever this device thinks. */
function localParts(now, timezone) {
  if (!timezone) return { hour: now.getHours(), minute: now.getMinutes() };
  try {
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: timezone,
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(now);
    const value = (type) =>
      Number(parts.find((part) => part.type === type)?.value ?? 0);
    return { hour: value('hour') % 24, minute: value('minute') };
  } catch {
    // An unknown timezone is not a reason to stop reminding anybody.
    return { hour: now.getHours(), minute: now.getMinutes() };
  }
}

/**
 * @param {{doses?: Array<object>, reminders?: Array<object>, ready?: boolean,
 *   timezone?: string|null}} [day]
 *   today's dose events and active reminders; `ready` is false while loading
 * @returns {{nudge: object|null, dismiss: () => void, spoken: (key: string) => void}}
 */
export function useProactive(day = {}) {
  const { doses = [], reminders = [], ready = true, timezone = null } = day;
  const [nudge, setNudge] = useState(null);
  // A nudge is raised once even if this re-runs while it is still on screen.
  const raisedRef = useRef(false);
  // When each due candidate was first noticed, so voice can wait
  // `VOICE_FOLLOW_SECONDS` behind the notification rather than racing it. A
  // plain ref, not persisted: the worst a reload does is let one nudge speak a
  // few seconds sooner than intended, which is not worth the complexity of
  // saving it.
  const firstSeenRef = useRef({});

  const dismiss = useCallback(() => {
    setNudge(null);
    raisedRef.current = false;
  }, []);

  useEffect(() => {
    // One at a time. A nudge nobody has dismissed used to block every later
    // one for the whole session; it now clears itself once it has had its say,
    // so the next thing that comes due is still spoken about.
    if (!ready || nudge) return undefined;
    const settings = getSettings();
    if (settings.proactive?.enabled === false) return undefined;

    const check = () => {
      const now = new Date();
      // Their evening, not this device's. The rest of this file was moved onto
      // the person's own timezone and this line was left behind, so a phone in
      // the wrong place could go quiet in the middle of their afternoon.
      const { hour } = localParts(now, timezone || undefined);
      if (hour < QUIET_END_HOUR || hour >= QUIET_START_HOUR) return;

      const zone = timezone || undefined;
      // Doses first: they are the ones with a consequence.
      const candidates = [
        ...doses
          // `missed` is in this list on purpose. It was not, and the effect was
          // that the doses most worth a word were the only ones she never
          // mentioned: a dose goes from late to missed on a timer, so anybody
          // who did not look at their phone for an hour got silence about the
          // one thing they had forgotten. It is still mentioned once, kindly,
          // and never again that day.
          .filter((dose) =>
            ['due', 'reminded', 'late', 'missed'].includes(dose.status)
          )
          .map((dose) => ({
            key: `dose:${dose.id}`,
            doseId: dose.id,
            at: dose.scheduled_local_time,
            // The moment it's due, same as the notification for it — see
            // `VOICE_FOLLOW_SECONDS`, which is what actually keeps this from
            // interrupting someone the instant the clock ticks over.
            after: 0,
            title: `${dose.medication_name || 'Your medicine'} is still waiting`,
            // What she is told, not what she must say. The facts are the app's;
            // the sentence is hers.
            brief:
              '[You are starting this conversation, not them. Nothing has been ' +
              `said to you yet. Their ${dose.medication_name || 'medicine'} was ` +
              `due at ${dose.scheduled_local_time} and has not been recorded ` +
              'either way. Say that once, kindly, in one short sentence, then ' +
              'stop and let them answer. Do not tell them what to do about it.]',
          })),
        ...reminders
          .filter((reminder) => reminder.status === 'active')
          .map((reminder) => ({
            key: `reminder:${reminder.id}`,
            reminderId: reminder.id,
            at: reminder.local_time,
            // A one-off is a timer somebody set for a reason — "in five
            // minutes" means five minutes, not twenty-five. A daily routine
            // keeps the grace period.
            after: reminder.effective_to ? 0 : OVERDUE_MINUTES,
            title: reminder.title,
            // Worded as a delivery, not a proposal. "They asked to be
            // reminded to drink water" was read as an errand and answered
            // with "shall I set that up for you?" — an offer to set the
            // reminder that was, at that moment, going off. What she has to
            // do here is say the thing.
            brief:
              '[You are starting this conversation, not them. Nothing has been ' +
              'said to you yet. This is a reminder they set earlier and it is ' +
              `due now: ${reminder.title}. Tell them it is time to ` +
              `${reminder.title}, once, lightly, in one short sentence, and ` +
              'then stop and let them answer. The reminder already exists — ' +
              'do not offer to create one, and do not ask whether they want ' +
              'to be reminded.]',
          })),
      ];

      const stillCandidate = new Set(candidates.map((candidate) => candidate.key));
      for (const key of Object.keys(firstSeenRef.current)) {
        if (!stillCandidate.has(key)) delete firstSeenRef.current[key];
      }

      for (const candidate of candidates) {
        const late = minutesPast(candidate.at, now, zone);
        if (late === null || late < candidate.after) continue;
        if (alreadySaid(candidate.key)) continue;
        // First noticed due, not fired yet: let the notification for the same
        // dose or reminder land first, and follow it a few seconds later
        // rather than speaking over it.
        const firstSeenAt = firstSeenRef.current[candidate.key] ?? now.getTime();
        firstSeenRef.current[candidate.key] = firstSeenAt;
        if (now.getTime() - firstSeenAt < VOICE_FOLLOW_SECONDS * 1000) continue;
        // Deliberately *not* marked as said here. It used to be, and the
        // consequence was silent and total: if the session then failed to open
        // — microphone refused, token mint failed, socket dropped — that dose
        // was recorded as spoken about and never came up again that day. The
        // caller marks it once she has actually said something.
        raisedRef.current = true;
        setNudge({ ...candidate, minutesLate: late });
        return;
      }
    };

    check();
    // Frequent enough that "a few seconds behind the notification" actually
    // means a few seconds — a once-a-minute tick would swallow that delay in
    // its own polling interval.
    const timer = setInterval(check, 5_000);
    return () => clearInterval(timer);
  }, [doses, reminders, ready, nudge, timezone]);

  // The thing it is about was recorded — out loud, on this screen, or on
  // another device. Either way the card is now describing something that is
  // not true, and nobody should have to dismiss it.
  useEffect(() => {
    if (!nudge) return;
    if (nudge.doseId) {
      const dose = doses.find((row) => row.id === nudge.doseId);
      if (!dose || !['due', 'reminded', 'late', 'missed'].includes(dose.status)) {
        setNudge(null);
        raisedRef.current = false;
      }
      return;
    }
    if (nudge.reminderId) {
      const reminder = reminders.find((row) => row.id === nudge.reminderId);
      if (!reminder || reminder.status !== 'active') {
        setNudge(null);
        raisedRef.current = false;
      }
    }
  }, [nudge, doses, reminders]);

  return { nudge, dismiss, spoken: remember };
}
