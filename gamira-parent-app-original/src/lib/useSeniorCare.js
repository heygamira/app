import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/lib/AuthContext';
import {
  doses as dosesApi,
  emergencyContacts as contactsApi,
  healthReadings as healthApi,
  reminders as remindersApi,
} from '@/api/gamiraClient';

// How often the screens re-read the record. Anything written elsewhere — a
// medicine added in the dashboard, a reading sent by a paired watch — appears
// within this window. 0 disables polling entirely.
const POLL_MS = Number(import.meta.env.VITE_POLL_MS ?? 0) || 0;

/**
 * Load the signed-in person's own care data.
 *
 * The Parent App is one person's device, so every request here is scoped to
 * `self` — the senior profile linked to the signed-in user. The backend
 * authorises each one against family membership; this hook cannot widen that.
 *
 * @param {{doses?: boolean, reminders?: boolean, readings?: boolean, contacts?: boolean, refreshMs?: number}} want
 */
export function useSeniorCare(want = {}) {
  const { self } = useAuth();
  const seniorId = self?.id;

  const [doses, setDoses] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [readings, setReadings] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const {
    doses: wantDoses,
    reminders: wantReminders,
    readings: wantReadings,
    contacts: wantContacts,
    refreshMs = POLL_MS,
  } = want;

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!seniorId) {
      setLoading(false);
      return;
    }
    // A background refresh must not blank the screen the person is reading.
    if (!quiet) setLoading(true);
    try {
      const [d, r, h, c] = await Promise.all([
        wantDoses ? dosesApi.list(seniorId) : Promise.resolve([]),
        wantReminders ? remindersApi.list(seniorId) : Promise.resolve([]),
        wantReadings ? healthApi.list(seniorId, { limit: 200 }) : Promise.resolve([]),
        wantContacts ? contactsApi.list(seniorId) : Promise.resolve([]),
      ]);
      setDoses(d);
      setReminders(r);
      setReadings(h);
      setContacts(c);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [seniorId, wantDoses, wantReminders, wantReadings, wantContacts]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!refreshMs || !seniorId) return undefined;
    const timer = setInterval(() => load({ quiet: true }), refreshMs);
    return () => clearInterval(timer);
  }, [load, refreshMs, seniorId]);

  return { self, seniorId, doses, reminders, readings, contacts, loading, error, reload: load };
}

export default useSeniorCare;
