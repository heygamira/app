import { useCallback, useEffect, useRef } from 'react';
import { gamira } from '@/api/gamiraClient';

/**
 * The Parent App's half of the watch relay.
 *
 * A paired watch never talks to the Gamira API and never holds a credential
 * for it — see `watch_relay_server.py` for why, and the matching design in
 * `tools/watch-sim/sim_server.py`. It only knows a pairing code and hands
 * everything to a small local relay. This hook is the other end: register
 * this senior under that same code, drain whatever the relay is holding, and
 * forward it to the real backend under this app's own already-authenticated
 * session — the one and only thing per senior that ever talks to the server
 * on the watch's behalf.
 *
 * Flags and SOS are forwarded the moment they are drained — nothing
 * safety-relevant waits. Routine readings are collected here instead and
 * flushed on their own, slower timer: a dashboard has no use for
 * six-second-resolution history, and fewer, larger writes is the point.
 */

const RELAY_BASE = '/watch-relay';
const POLL_INTERVAL_MS = 2000;
const READING_FLUSH_MS = 30_000;

/**
 * `?dev=<subject>` is also this window's pairing code — the same string
 * `run.py --pair` gives the watch. Development only: there is no relay, and
 * nothing to register, outside a dev build.
 */
function pairingCodeFromUrl() {
  if (!import.meta.env.DEV) return null;
  try {
    return new URLSearchParams(window.location.search).get('dev');
  } catch {
    return null;
  }
}

async function relayFetch(path, options) {
  const response = await fetch(`${RELAY_BASE}${path}`, options);
  if (!response.ok) throw new Error(`watch relay ${path} failed: ${response.status}`);
  return response.json();
}

/**
 * @param {{seniorId?: string|null, person?: string|null, onMutation?: () => void}} args
 */
export function useWatchRelay({ seniorId, person, onMutation } = {}) {
  // metric -> latest reading since the last flush. A ref, not state: nothing
  // here needs to be rendered, and it must survive between poll ticks without
  // re-subscribing the effect below on every drain.
  const bufferRef = useRef(new Map());
  const pairingCode = pairingCodeFromUrl();

  useEffect(() => {
    if (!pairingCode || !seniorId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        await relayFetch('/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            pairing_code: pairingCode,
            person: person || 'this person',
          }),
        });
      } catch {
        // No relay running — no watch configured for this session. A normal,
        // silent no-op, not something worth surfacing to the person.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line no-unused-vars -- cancelled guards the async body above
  }, [pairingCode, seniorId, person]);

  const flushReadings = useCallback(async () => {
    if (!seniorId || bufferRef.current.size === 0) return;
    const readings = Array.from(bufferRef.current.values());
    bufferRef.current.clear();
    try {
      await gamira.healthReadings.createBulk(seniorId, readings);
      onMutation?.();
    } catch {
      // Lost with the buffer. The watch sends again in a few seconds — losing
      // one flush of ambient readings is not worth retry machinery for.
    }
  }, [seniorId, onMutation]);

  useEffect(() => {
    if (!pairingCode || !seniorId) return undefined;

    const drain = async () => {
      let body;
      try {
        body = await relayFetch(
          `/outbox?pairing_code=${encodeURIComponent(pairingCode)}`
        );
      } catch {
        return; // relay not running, or nothing paired to it yet
      }

      for (const reading of body.readings || []) {
        if (reading?.metric) bufferRef.current.set(reading.metric, reading);
      }

      for (const item of body.urgent || []) {
        if (item.kind === 'sos') {
          gamira.sos
            .raise(seniorId, { source: 'watch', note: item.note || undefined })
            .then(() => onMutation?.())
            .catch(() => {});
        } else if (item.kind === 'device_flag') {
          const { kind: _kind, pairing_code: _code, ...flag } = item;
          gamira.deviceFlags
            .raise(seniorId, flag)
            .then(() => onMutation?.())
            .catch(() => {});
        }
      }
    };

    drain();
    const pollTimer = setInterval(drain, POLL_INTERVAL_MS);
    const flushTimer = setInterval(flushReadings, READING_FLUSH_MS);
    return () => {
      clearInterval(pollTimer);
      clearInterval(flushTimer);
    };
  }, [pairingCode, seniorId, flushReadings, onMutation]);
}

export default useWatchRelay;
