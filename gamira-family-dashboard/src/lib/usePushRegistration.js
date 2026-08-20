import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken, onMessage } from 'firebase/messaging';
import { Capacitor } from '@capacitor/core';
import { FirebaseMessaging } from '@capacitor-firebase/messaging';
import { firebaseEnabled, messaging } from '@/lib/firebase';
import { gamira } from '@/api/gamiraClient';

// A NEW key, deliberately not one of the existing auth/family/senior keys:
// this identifies a *browser installation*, not a signed-in person, and has
// to survive sign-out/sign-in on the same machine so re-registering doesn't
// mint a second device row for it.
const INSTALL_ID_KEY = 'gamira_install_id';

function getOrCreateInstallId() {
  try {
    const existing = localStorage.getItem(INSTALL_ID_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    localStorage.setItem(INSTALL_ID_KEY, created);
    return created;
  } catch {
    // Private browsing (storage throws), or no `crypto.randomUUID`. Push
    // registration still works — this browser just looks like a new
    // installation next time instead of updating the same row.
    return `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

// Capacitor's permission states ('granted' | 'denied' | 'prompt' |
// 'prompt-with-rationale') don't match the web Notification API's
// ('granted' | 'denied' | 'default') that the rest of this hook — and
// Settings.jsx's toggle — already speak, so every native permission read
// goes through this.
function mapNativePermission(receive) {
  if (receive === 'granted') return 'granted';
  if (receive === 'denied') return 'denied';
  return 'default';
}

/**
 * Registers this device for push delivery, and re-registers it silently on
 * every mount once permission has already been granted — the backend's own
 * `POST /devices` docstring calls that "safe to call on every app start."
 *
 * On native Android, registration goes through `@capacitor-firebase/messaging`
 * (real FCM) rather than the web Push API: a Capacitor WebView can run the
 * web path (it has Service Worker/PushManager support), but that path is
 * unreliable once the app is backgrounded or killed — no browser process is
 * left to wake it. SOS delivery in that state relies on FCM reaching native
 * code directly; see android's GamiraFirebaseMessagingService.
 *
 * `onForegroundMessage` fires for a message that arrives while this tab is
 * focused: FCM never runs the service worker's background handler for that
 * case, so a focused tab has to notice on its own. Callers pass in whatever
 * their existing refresh function is (e.g. `useAlerts()`'s `reload`) rather
 * than this hook inventing its own notification UI. Native has no equivalent
 * wiring — the SSE stream in `useAlerts.js` already reloads on any family
 * event while the app is foregrounded, for every notification type, not
 * just push-carried ones.
 *
 * @param {{onForegroundMessage?: () => void}} [options]
 */
export function usePushRegistration({ onForegroundMessage } = {}) {
  const isNative = Capacitor.isNativePlatform();

  const supported = isNative
    ? firebaseEnabled
    : firebaseEnabled &&
      Boolean(messaging) &&
      Boolean(import.meta.env.VITE_FIREBASE_VAPID_KEY) &&
      typeof navigator !== 'undefined' &&
      'serviceWorker' in navigator &&
      typeof window !== 'undefined' &&
      'PushManager' in window;

  const [installId] = useState(getOrCreateInstallId);
  const [permission, setPermission] = useState(() => {
    if (isNative) return 'default'; // resolved async by the mount effect below
    return typeof Notification !== 'undefined' ? Notification.permission : 'default';
  });
  // idle -> registering -> registered, or error at any point along the way.
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState(null);
  // Guards against the mount effect and a deliberate `enable()` overlapping.
  const registeringRef = useRef(false);

  const runRegistration = useCallback(async () => {
    if (!supported || registeringRef.current) return;
    registeringRef.current = true;
    setStatus('registering');
    setError(null);
    try {
      const token = isNative ? await getNativeToken() : await getWebToken();
      if (!token) {
        throw new Error('The device did not return a push token.');
      }
      await gamira.devices.register({
        install_id: installId,
        platform: isNative ? 'android' : 'web',
        push_token: token,
        locale: navigator.language,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      setStatus('registered');
    } catch (err) {
      setStatus('error');
      setError(err?.message || 'Could not turn on push notifications.');
    } finally {
      registeringRef.current = false;
    }
  }, [supported, installId, isNative]);

  const enable = useCallback(async () => {
    if (!supported) return;
    try {
      if (isNative) {
        const { receive } = await FirebaseMessaging.requestPermissions();
        const mapped = mapNativePermission(receive);
        setPermission(mapped);
        if (mapped === 'granted') {
          await runRegistration();
        }
        return;
      }
      if (typeof Notification === 'undefined') return;
      const result = await Notification.requestPermission();
      setPermission(result);
      if (result === 'granted') {
        await runRegistration();
      }
      // 'denied' is terminal and shown as-is by the caller; nothing here
      // retries it automatically.
    } catch (err) {
      setStatus('error');
      setError(err?.message || 'Could not request notification permission.');
    }
  }, [supported, runRegistration, isNative]);

  // Silent re-registration: permission was already granted on a previous
  // visit/install, so this repeats the flow with no dialog — neither
  // `checkPermissions()` nor `requestPermission()` re-prompts once a
  // decision already exists.
  useEffect(() => {
    if (!supported) return;
    if (isNative) {
      FirebaseMessaging.checkPermissions()
        .then(({ receive }) => {
          const mapped = mapNativePermission(receive);
          setPermission(mapped);
          if (mapped === 'granted') runRegistration();
        })
        .catch(() => {});
      return;
    }
    if (permission === 'granted') {
      runRegistration();
    }
    // Deliberately only on mount (and if `supported` only becomes true once
    // Firebase finishes initializing): a fresh grant is `enable()`'s job, not
    // this effect's, so `permission` and `runRegistration` are excluded from
    // the dependency list on purpose.
  }, [supported, isNative]);

  // Foreground delivery on the web: a focused tab never gets
  // `onBackgroundMessage`. Native has no equivalent — see the hook doc above.
  useEffect(() => {
    if (isNative || !supported || !messaging) return undefined;
    return onMessage(messaging, () => {
      onForegroundMessage?.();
    });
  }, [isNative, supported, onForegroundMessage]);

  return { supported, permission, status, error, enable, refresh: runRegistration };
}

async function getWebToken() {
  const swParams = new URLSearchParams({
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY || '',
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || '',
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || '',
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || '',
    messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '',
    appId: import.meta.env.VITE_FIREBASE_APP_ID || '',
  });
  const registration = await navigator.serviceWorker.register(
    `/firebase-messaging-sw.js?${swParams}`
  );
  return getToken(messaging, {
    vapidKey: import.meta.env.VITE_FIREBASE_VAPID_KEY,
    serviceWorkerRegistration: registration,
  });
}

async function getNativeToken() {
  const { token } = await FirebaseMessaging.getToken();
  return token;
}

export default usePushRegistration;
