import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken, onMessage } from 'firebase/messaging';
import { firebaseEnabled, messaging } from '@/lib/firebase';
import { gamira } from '@/api/gamiraClient';
import { useVoice } from '@/lib/VoiceContext';

// Separate from the session token: this survives sign-out/sign-in, so the
// backend updates one device row for this browser instead of creating a new
// one on every visit. See `DeviceRegister.install_id` in the backend schema.
const INSTALL_ID_KEY = 'gamira_install_id';
const VAPID_KEY = import.meta.env.VITE_FIREBASE_VAPID_KEY;

const FIREBASE_ENV = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

// A file under `public/` can't read `import.meta.env` — it's served as-is,
// never processed by Vite — so the real values are handed over as query
// params when the page registers it. None of this is secret; see the
// comment in `src/lib/firebase.js`.
function serviceWorkerUrl() {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(FIREBASE_ENV)) {
    params.set(key, value || '');
  }
  return `/firebase-messaging-sw.js?${params.toString()}`;
}

function getInstallId() {
  try {
    const existing = localStorage.getItem(INSTALL_ID_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    localStorage.setItem(INSTALL_ID_KEY, created);
    return created;
  } catch {
    // Storage unavailable (private browsing, quota). Still usable this once,
    // just not stable across a reload — registering again next load simply
    // creates a fresh device row rather than updating this one.
    return crypto.randomUUID();
  }
}

/**
 * Push notification registration: permission, an FCM token, and telling the
 * backend about it.
 *
 * This is a senior's own device, so it never nags. It asks for permission
 * exactly once, when `enable()` is called from the Notifications toggle, and
 * a browser `denied` decision is shown on screen as an explanation rather
 * than retried — there is no path in this hook that asks again on its own.
 *
 * The one thing it does automatically is re-register on every mount once
 * permission is already `granted`. That fires no dialog — the browser only
 * asks once — and it is what the backend's own `POST /devices` docstring
 * calls out as safe and expected: a rotated token or a reinstalled app stays
 * current without the person doing anything.
 *
 * @returns {{
 *   supported: boolean,
 *   permission: 'default'|'granted'|'denied'|'unsupported',
 *   status: 'idle'|'registering'|'registered'|'error',
 *   error: string|null,
 *   enable: () => Promise<void>,
 * }}
 */
export function usePushRegistration() {
  // The data-refresh path every other live-update source in this app already
  // uses (see `onWatchRelayMutation` and `onMutation` in VoiceContext) — a
  // foreground push means "something changed", and this is how that becomes
  // "the screen shows it" without inventing a second notion of freshness.
  const { reload } = useVoice();

  const supported =
    firebaseEnabled &&
    Boolean(messaging) &&
    Boolean(VAPID_KEY) &&
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    typeof window !== 'undefined' &&
    'PushManager' in window &&
    typeof Notification !== 'undefined';

  const [permission, setPermission] = useState(
    /** @type {'default'|'granted'|'denied'|'unsupported'} */
    (supported ? Notification.permission : 'unsupported')
  );
  const [status, setStatus] = useState(
    /** @type {'idle'|'registering'|'registered'|'error'} */ ('idle')
  );
  const [error, setError] = useState(/** @type {string|null} */ (null));
  const registeringRef = useRef(false);

  const registerToken = useCallback(async () => {
    // Re-entrancy guard, not a cache: the mount effect and a manual `enable()`
    // tap can land in the same tick, and a second registration racing the
    // first would just be a duplicate `POST /devices` for no benefit.
    if (registeringRef.current) return;
    registeringRef.current = true;
    setStatus('registering');
    setError(null);
    try {
      const registration = await navigator.serviceWorker.register(serviceWorkerUrl());
      const token = await getToken(messaging, {
        vapidKey: VAPID_KEY,
        serviceWorkerRegistration: registration,
      });
      if (!token) {
        throw new Error('No notification token was issued for this browser.');
      }
      await gamira.devices.register({
        install_id: getInstallId(),
        platform: 'web',
        push_token: token,
        locale: navigator.language,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      setStatus('registered');
    } catch (e) {
      setStatus('error');
      setError(e?.message || 'Could not turn on notifications.');
    } finally {
      registeringRef.current = false;
    }
  }, []);

  const enable = useCallback(async () => {
    if (!supported) return;
    try {
      const result = await Notification.requestPermission();
      setPermission(result);
      if (result === 'granted') await registerToken();
    } catch (e) {
      setStatus('error');
      setError(e?.message || 'Could not ask for notification permission.');
    }
  }, [supported, registerToken]);

  useEffect(() => {
    if (supported && Notification.permission === 'granted') {
      registerToken();
    }
  }, [supported, registerToken]);

  // Foreground delivery: the app is already open, so there is no lock-screen
  // notification to show — just bring the screen currently up to date.
  useEffect(() => {
    if (!supported) return undefined;
    return onMessage(messaging, () => {
      reload({ quiet: true });
    });
  }, [supported, reload]);

  return { supported, permission, status, error, enable };
}

export default usePushRegistration;
