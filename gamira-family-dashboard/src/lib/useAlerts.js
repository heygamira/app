import { useCallback, useEffect, useState } from "react";
import {
  alerts as alertsApi,
  events as eventsApi,
  notifications as notificationsApi,
} from "@/api/gamiraClient";
import { useAuth } from "@/lib/AuthContext";
import { usePoll } from "@/lib/usePoll";

// A live SSE connection (see gamiraClient's `events.stream`) now delivers an
// SOS or a device flag the instant it happens — this is a safety net, not the
// primary path, for whenever that connection is silently down (a dropped
// network, a server restart mid-reconnect). Slow on purpose: the whole point
// of the stream is that this no longer has to be a few seconds.
const ALERT_SAFETY_POLL_MS = 60_000;
// How long to wait before trying to reconnect a dropped event stream.
const RECONNECT_DELAY_MS = 3000;

// An SOS and its escalations are the same emergency. A repeat must raise the
// same red banner, or "nobody answered" would be quieter than the first press.
const isEmergency = (row) => row.type === "sos" || row.type === "sos_escalation";

/**
 * A notice raised by a paired device — never an emergency.
 *
 * Also covers the two things Gamira raises about a person without anybody
 * pressing anything: nobody answering after a watch flag, and an alert being
 * withdrawn because they said they were alright. Both belong in the amber
 * band, and neither may ever wear the red one.
 */
const isDeviceNotice = (row) =>
  (row.type === "family_update" &&
    (row.related_entity_type === "health_reading" ||
      row.related_entity_type === "alert")) ||
  row.type === "wellbeing_check";

/**
 * Unacknowledged alerts for the signed-in member, newest first, split by what
 * they actually are:
 *
 *   sos     — a person pressed the button. Red, interrupting.
 *   notices — a watch reported a reading outside the limits set on it, nobody
 *             answered when Gamira asked about one, or somebody withdrew their
 *             own alert. Amber, dismissible, attributed to whoever said it.
 *
 * The split is the whole point and is worth defending: a watch left on a
 * bedside table leaves its band most nights, and if that arrived wearing the
 * red full-screen alarm a family would learn within a week to dismiss the red
 * full-screen alarm. The one that matters is the one they would stop looking
 * at.
 *
 * The backend has already decided who may see each one: the notification list
 * only ever returns the caller's own rows.
 */
export function useAlerts() {
  const { activeFamily } = useAuth();
  const familyId = activeFamily?.id;
  const [rows, setRows] = useState([]);

  const load = useCallback(async () => {
    let fresh;
    try {
      fresh = await notificationsApi.list({ unreadOnly: true, limit: 30 });
    } catch {
      // A failed poll is not worth a banner; the next one recovers. The
      // screen's own error state still reports a broken connection.
      return;
    }

    // An emergency the person has since withdrawn — they pressed it by
    // accident, or the countdown ran out while they were fetching their
    // glasses, and they have told Gamira they are alright. Leaving the red
    // overlay up and the alarm looping after that would be worse than not
    // having shown it: it would be the app insisting on an emergency the
    // person has explicitly said is over.
    //
    // The notice explaining the cancellation arrives through this same list,
    // so nothing disappears without a word.
    const emergencies = fresh.filter(
      (row) => isEmergency(row) && row.related_entity_type === "alert"
    );
    if (emergencies.length) {
      const states = await Promise.all(
        emergencies.map((row) =>
          alertsApi
            .get(row.related_entity_id)
            .then((alert) => [row.related_entity_id, alert.status])
            .catch(() => [row.related_entity_id, null])
        )
      );
      // Acknowledged counts too: somebody in the family has said they are on
      // it, and that is exactly when everybody else's alarm should stop.
      const done = new Set(["cancelled", "resolved", "acknowledged"]);
      const closed = new Set(
        states.filter(([, status]) => done.has(status)).map(([id]) => id)
      );
      if (closed.size) {
        fresh = fresh.filter(
          (row) => !(isEmergency(row) && closed.has(row.related_entity_id))
        );
      }
    }
    setRows(fresh);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The primary path: reconnects on its own if the connection drops, with a
  // short fixed delay rather than exponential backoff — a dashboard tab
  // reconnecting a few seconds too eagerly after a blip costs nothing that
  // matters, and simplicity here is worth more than tuning a backoff curve
  // for a connection that is expected to just stay up.
  useEffect(() => {
    if (!familyId) return undefined;
    const controller = new AbortController();
    let stopped = false;

    (async () => {
      while (!stopped) {
        try {
          // eslint-disable-next-line no-unused-vars -- the event's *arrival*
          // is the signal; its contents are re-fetched from the real list.
          for await (const _event of eventsApi.stream(familyId, {
            signal: controller.signal,
          })) {
            load();
          }
        } catch {
          // Dropped, or the family changed under us. Either way, reconnect
          // below unless this effect has since been torn down.
        }
        if (stopped) return;
        await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS));
      }
    })();

    return () => {
      stopped = true;
      controller.abort();
    };
  }, [familyId, load]);

  usePoll(load, ALERT_SAFETY_POLL_MS);

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
    // Every unread notification about the *same* alert, not just the one that
    // was tapped. A press and each of its escalations write their own row, so
    // dismissing one only revealed the next — and a testing afternoon leaves
    // a dozen. From behind the overlay that reads as an alert that will not
    // close from anything, which is roughly the worst thing a red full-screen
    // dialog can do.
    const alertId = row?.related_entity_type === "alert" && row.related_entity_id;
    const together = alertId
      ? rows.filter(
          (item) =>
            item.related_entity_type === "alert" &&
            item.related_entity_id === alertId
        )
      : [row].filter(Boolean);

    // Optimistic: the banner must close on the first tap, not after a
    // round-trip. A failed call reappears on the next poll.
    const dismissed = new Set(together.map((item) => item.id));
    setRows((current) => current.filter((item) => !dismissed.has(item.id)));
    await Promise.all(
      together.map((item) =>
        notificationsApi.markOpened(item.id).catch(() => {
          /* the next poll re-raises it */
        })
      )
    );
    // Anything backed by a real alert row gets acknowledged, not only the red
    // ones. A wellbeing check escalates exactly like an SOS does — that is the
    // point of reusing the lifecycle — so dismissing its banner without
    // acknowledging would leave the family being re-notified about something
    // one of them has already looked at.
    if (row && row.related_entity_type === "alert" && row.type !== "family_update") {
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
