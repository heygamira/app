import { Capacitor } from '@capacitor/core';
import { LocalNotifications } from '@capacitor/local-notifications';
import { minutesUntil } from '@/lib/schedule';
import { OPEN_DOSE_STATUSES } from '@/api/parentData';

// Deliberately no quiet-hours check here (compare src/lib/useProactive.js's
// QUIET_END_HOUR/QUIET_START_HOUR) — that convention silences the *voice*
// nudge at night; a missed-dose alert must not be, since AGENTS.md requires
// reminders to keep working with no AI/network involved at all.

const CHANNEL_ID = 'gamira-reminders';

// LocalNotifications ids are int32. A dose id (a UUID string) is hashed down
// to a stable positive int so the same dose always maps to the same native
// notification id — required for a later `cancel()` to hit the exact alarm
// a prior `schedule()` created.
function idFor(doseId) {
  let hash = 0x811c9dc5; // FNV-1a
  const str = String(doseId);
  for (let i = 0; i < str.length; i += 1) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash & 0x7fffffff;
}

function isNative() {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === 'android';
}

/**
 * Reconcile native scheduled notifications with the current doses: schedule
 * one for every still-open, still-upcoming dose; cancel anything scheduled
 * that is no longer open or no longer present. Safe to call on every reload
 * — idempotent, and never throws (a scheduling failure must never surface as
 * a screen error; the in-app due/late/missed badges already carry the same
 * information without any native alarm).
 */
export async function syncDoseNotifications(doses, timezone) {
  if (!isNative()) return;
  try {
    const upcoming = (doses || []).filter((dose) => {
      if (!OPEN_DOSE_STATUSES.includes(dose.status)) return false;
      const delta = minutesUntil(dose.scheduled_local_time, timezone);
      return delta !== null && delta >= 0;
    });

    const wantedIds = new Map(upcoming.map((dose) => [idFor(dose.id), dose]));

    const { notifications: pending } = await LocalNotifications.getPending();
    const toCancel = pending.filter((n) => !wantedIds.has(n.id));
    if (toCancel.length) {
      await LocalNotifications.cancel({ notifications: toCancel.map((n) => ({ id: n.id })) });
    }

    const pendingIds = new Set(pending.map((n) => n.id));
    const toSchedule = [...wantedIds.entries()]
      .filter(([id]) => !pendingIds.has(id))
      .map(([id, dose]) => ({
        id,
        title: 'Time for your medicine',
        body: dose.dose_quantity ? `${dose.medication_name} · ${dose.dose_quantity}` : dose.medication_name,
        schedule: { at: new Date(Date.now() + minutesUntil(dose.scheduled_local_time, timezone) * 60_000) },
        channelId: CHANNEL_ID,
        extra: { type: 'medication_reminder', doseId: dose.id },
      }));
    if (toSchedule.length) {
      await LocalNotifications.schedule({ notifications: toSchedule });
    }
  } catch (e) {
    console.warn('Could not sync local dose notifications.', e);
  }
}

/** Cancel every locally-scheduled dose notification. Called on sign-out. */
export async function cancelAllDoseNotifications() {
  if (!isNative()) return;
  try {
    const { notifications: pending } = await LocalNotifications.getPending();
    if (pending.length) {
      await LocalNotifications.cancel({ notifications: pending.map((n) => ({ id: n.id })) });
    }
  } catch (e) {
    console.warn('Could not cancel local dose notifications.', e);
  }
}
