import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken, onMessage } from 'firebase/messaging';
import { Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { firebaseEnabled, messaging } from '@/lib/firebase';
import { gamira } from '@/api/gamiraClient';
import { useVoice } from '@/lib/VoiceContext';

// Separate from the session token: this survives sign-out/sign-in, so the
// backend updates one device row for this browser instead of creating a new
// one on every visit. See `DeviceRegister.install_id` in the backend schema.
const INSTALL_ID_KEY = 'gamira_install_id';
const VAPID_KEY = import.meta.env.VITE_FIREBASE_VAPID_KEY;
const REMINDER_CHANNEL_ID = 'gamira-reminders';

const isNative = Capacitor.isNativePlatform();

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

// One channel: the backend's push payload types (medication_reminder,
// missed_dose, reminder, family_update) carry no urgency signal today, so a
// second channel would just be unused surface area. Safe to call repeatedly.
async function createReminderChannel() {
  if (Capacitor.getPlatform() !== 'android') return;
  try {
    await PushNotifications.createChannel({
      id: REMINDER_CHANNEL_ID,
      name: 'Reminders',
      description: 'Medicine and reminder alerts',
      importance: 5,
      visibility: 1,
      vibration: true,
    });
  } catch {
    // Non-fatal: worst case the OS falls back to its default channel.
  }
}

// Native counterpart of the web `getToken(messaging, ...)` call below — asks
// the OS for permission, then resolves the FCM registration token via the
// native SDK (wired through android/app/google-services.json).
function registerNativeToken() {
  return new Promise((resolve, reject) => {
    let regSub;
    let errSub;
    const cleanup = () => {
      regSub?.then((s) => s.remove());
      errSub?.then((s) => s.remove());
    };
    regSub = PushNotifications.addListener('registration', (token) => {
      cleanup();
      resolve(token.value);
    });
    errSub = PushNotifications.addListener('registrationError', (err) => {
      cleanup();
      reject(new Error(err?.error || 'Push registration failed.'));
    });
    PushNotifications.register();
  });
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
 * Inside the native Android build, the OS-level `@capacitor/push-notifications`
 * plugin stands in for the web Firebase SDK + service worker path — see
 * `registerNativeToken`/`createReminderChannel` above — but the shape this
 * hook returns, and every screen that consumes it, stays identical either
 * way.
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
    isNative ||
    (firebaseEnabled &&
      Boolean(messaging) &&
      Boolean(VAPID_KEY) &&
      typeof navigator !== 'undefined' &&
      'serviceWorker' in navigator &&
      typeof window !== 'undefined' &&
      'PushManager' in window &&
      typeof Notification !== 'undefined');

  const [permission, setPermission] = useState(
    /** @type {'default'|'granted'|'denied'|'unsupported'} */
    (isNative ? 'default' : supported ? Notification.permission : 'unsupported')
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
      let token;
      if (isNative) {
        await createReminderChannel();
        token = await registerNativeToken();
      } else {
        const registration = await navigator.serviceWorker.register(serviceWorkerUrl());
        token = await getToken(messaging, {
          vapidKey: VAPID_KEY,
          serviceWorkerRegistration: registration,
        });
      }
      if (!token) {
        throw new Error('No notification token was issued for this device.');
      }
      await gamira.devices.register({
        install_id: getInstallId(),
        platform: isNative ? 'android' : 'web',
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
      if (isNative) {
        const result = await PushNotifications.requestPermissions();
        const granted = result.receive === 'granted';
        setPermission(granted ? 'granted' : 'denied');
        if (granted) await registerToken();
      } else {
        const result = await Notification.requestPermission();
        setPermission(result);
        if (result === 'granted') await registerToken();
      }
    } catch (e) {
      setStatus('error');
      setError(e?.message || 'Could not ask for notification permission.');
    }
  }, [supported, registerToken]);

  useEffect(() => {
    if (!supported) return;
    if (isNative) {
      PushNotifications.checkPermissions().then((result) => {
        const granted = result.receive === 'granted';
        setPermission(granted ? 'granted' : 'default');
        if (granted) registerToken();
      });
    } else if (Notification.permission === 'granted') {
      registerToken();
    }
  }, [supported, registerToken]);

  // Foreground delivery: the app is already open, so there is no lock-screen
  // notification to show — just bring the screen currently up to date.
  useEffect(() => {
    if (!supported) return undefined;
    if (isNative) {
      const subPromise = PushNotifications.addListener('pushNotificationReceived', () => {
        reload({ quiet: true });
      });
      return () => {
        subPromise.then((sub) => sub.remove());
      };
    }
    return onMessage(messaging, () => {
      reload({ quiet: true });
    });
  }, [supported, reload]);

  return { supported, permission, status, error, enable };
}

export default usePushRegistration;
