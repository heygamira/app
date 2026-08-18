import { useCallback, useEffect, useRef, useState } from 'react';
import { getSettings } from '@/lib/userSettings';
import { sortableTime } from '@/lib/schedule';

/**
 * Gamira speaking first.
 *
 * Everything else in this app waits to be asked. That is the wrong shape for
 * the one case that matters most: a dose that is late is late precisely
 * because nobody looked at the phone. A companion that only ever answers is no
 * use to somebody who has forgotten there is anything to ask about.
 *
 * So this watches the day that is already loaded and, when something has been
 * waiting long enough, says one short sentence out loud and puts a card on
 * screen. Deliberately small:
 *
 * - **It speaks, it does not listen.** No microphone, no Live session, no
 *   cost. `speechSynthesis` is local to the device. Opening a session on the
 *   app's own initiative would mean the microphone turning itself on in
 *   somebody's home, which is not a thing this app should ever do uninvited.
 * - **Once per thing, per day.** Remembered across reloads, because a nudge
 *   that repeats every time a screen mounts is nagging, and the persona
 *   forbids nagging for good reason.
 * - **Not at night.** The same courtesy the backend applies to family notices.
 * - **Never about a medicine's contents.** It says a name and a time, which
 *   is what is already on the screen, and nothing about what to do.
 *
 * Off by default is deliberately *not* the choice here — a reminder that has
 * to be discovered in Settings will not reach the person who needs it — but it
 * is one switch away in Settings › Voice.
 */

// How overdue something has to be before it is worth saying out loud. Short
// enough to be useful, long enough that somebody mid-breakfast is not
// interrupted about the tablet in their hand.
const OVERDUE_MINUTES = 20;
// Nothing is volunteered outside these local hours.
const QUIET_END_HOUR = 8;
const QUIET_START_HOUR = 21;
const STORE_KEY = 'gamira.proactive.spoken';

const today = () => new Date().toISOString().slice(0, 10);

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

/** Minutes since a local HH:MM today, or null if it is still ahead. */
function minutesPast(localTime, now) {
  const padded = sortableTime(localTime);
  if (padded === '99:99') return null;
  const [hours, minutes] = padded.split(':').map(Number);
  const due = new Date(now);
  due.setHours(hours, minutes, 0, 0);
  const delta = Math.round((now.getTime() - due.getTime()) / 60000);
  return delta >= 0 ? delta : null;
}

function speak(text) {
  if (!('speechSynthesis' in window)) return false;
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    // Unhurried, and a touch lower than the default. This is the same voice
    // the settings preview uses, so what somebody chose there is what they get.
    utterance.rate = 0.92;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

/**
 * @param {{doses?: Array<object>, reminders?: Array<object>, ready?: boolean}} [day]
 *   today's dose events and active reminders; `ready` is false while loading
 * @returns {{nudge: object|null, dismiss: () => void}}
 */
export function useProactive(day = {}) {
  const { doses = [], reminders = [], ready = true } = day;
  const [nudge, setNudge] = useState(null);
  // A nudge is spoken once even if this re-runs while it is still on screen.
  const spokenRef = useRef(false);

  const dismiss = useCallback(() => {
    setNudge(null);
    spokenRef.current = false;
  }, []);

  useEffect(() => {
    if (!ready || nudge) return undefined;
    const settings = getSettings();
    if (settings.proactive?.enabled === false) return undefined;

    const check = () => {
      const now = new Date();
      const hour = now.getHours();
      if (hour < QUIET_END_HOUR || hour >= QUIET_START_HOUR) return;

      // Doses first: they are the ones with a consequence.
      const candidates = [
        ...doses
          .filter((dose) => ['due', 'reminded', 'late'].includes(dose.status))
          .map((dose) => ({
            key: `dose:${dose.id}`,
            at: dose.scheduled_local_time,
            say:
              `It's a little past ${dose.scheduled_local_time} — ` +
              `your ${dose.medication_name || 'medicine'} is still waiting.`,
            title: `${dose.medication_name || 'Your medicine'} is still waiting`,
          })),
        ...reminders
          .filter((reminder) => reminder.status === 'active')
          .map((reminder) => ({
            key: `reminder:${reminder.id}`,
            at: reminder.local_time,
            say: `You wanted to ${reminder.title} around ${reminder.local_time}.`,
            title: reminder.title,
          })),
      ];

      for (const candidate of candidates) {
        const late = minutesPast(candidate.at, now);
        if (late === null || late < OVERDUE_MINUTES) continue;
        if (alreadySaid(candidate.key)) continue;
        remember(candidate.key);
        if (!spokenRef.current) {
          spokenRef.current = true;
          speak(candidate.say);
        }
        setNudge({ ...candidate, minutesLate: late });
        return;
      }
    };

    check();
    // A minute is fine: nothing here is urgent, and the card is a prompt to
    // look at a screen that is already showing the same thing.
    const timer = setInterval(check, 60_000);
    return () => clearInterval(timer);
  }, [doses, reminders, ready, nudge]);

  return { nudge, dismiss };
}
