import { useCallback, useEffect, useState } from "react";
import {
  alerts as alertsApi,
  notifications as notificationsApi,
} from "@/api/gamiraClient";
import { usePoll } from "@/lib/usePoll";

// Alerts are the one thing worth checking for more often than the rest of the
// screen. Still polling: the backend can send a push, but no FCM credentials
// exist and this app has no service worker, so an alert still only reaches a
// family member whose app is open.
const ALERT_POLL_MS = 4000;

// An SOS and its escalations are the same emergency. A repeat must raise the
// same red banner, or "nobody answered" would be quieter than the first press.
const isEmergency = (row) => row.type === "sos" || row.type === "sos_escalation";

/** A notice raised by a paired device — never an emergency. */
const isDeviceNotice = (row) =>
  row.type === "family_update" && row.related_entity_type === "health_reading";

/**
 * Unacknowledged alerts for the signed-in member, newest first, split by what
 * they actually are:
 *
 *   sos     — a person pressed the button. Red, interrupting.
 *   notices — a watch reported a reading outside the limits set on it. Amber,
 *             dismissible, and attributed to the device.
 *
 * The backend has already decided who may see each one: the notification list
 * only ever returns the caller's own rows.
 */
export function useAlerts() {
  const [rows, setRows] = useState([]);

  const load = useCallback(async () => {
    try {
      setRows(await notificationsApi.list({ unreadOnly: true, limit: 30 }));
    } catch {
      // A failed poll is not worth a banner; the next one recovers. The
      // screen's own error state still reports a broken connection.
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePoll(load, ALERT_POLL_MS);

  /**
   * Dismiss one notification, and — for an emergency — record that somebody
   * responded.
   *
   * Two different things, deliberately both done here. Marking the
   * notification read is per-member and tells nobody else anything.
   * Acknowledging the *alert* names who responded and when, stops the
   * escalation, and is visible to the whole family.
   */
  const acknowledge = useCallback(async (notificationId) => {
    const row = rows.find((candidate) => candidate.id === notificationId);
    // Optimistic: the banner must close on the first tap, not after a
    // round-trip. A failed call reappears on the next poll.
    setRows((current) => current.filter((item) => item.id !== notificationId));
    try {
      await notificationsApi.markOpened(notificationId);
    } catch {
      /* the next poll re-raises it */
    }
    if (row && isEmergency(row) && row.related_entity_type === "alert") {
      try {
        await alertsApi.acknowledge(row.related_entity_id);
      } catch {
        // The banner is already closed for this person. The alert stays
        // unacknowledged and keeps escalating, which is the safe direction.
      }
    }
  }, [rows]);

  return {
    sos: rows.filter(isEmergency),
    notices: rows.filter(isDeviceNotice),
    acknowledge,
    reload: load,
  };
}

export default useAlerts;
