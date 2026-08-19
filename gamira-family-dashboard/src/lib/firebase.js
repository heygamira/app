import { initializeApp, getApps } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';
import { getMessaging } from 'firebase/messaging';

// The web config is not a secret — it identifies the project, it doesn't
// authorize anything by itself. Safe to ship in the client bundle, unlike
// the actual secrets `.env.local`'s own comment warns about.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

// Firebase is optional locally: a checkout with no VITE_FIREBASE_* vars set
// still runs, just without the Google/email sign-in buttons — AUTH_MODE=dev
// and the dev-identity dropdown work either way.
export const firebaseEnabled = Boolean(firebaseConfig.apiKey && firebaseConfig.projectId);

export const firebaseApp = firebaseEnabled
  ? getApps()[0] || initializeApp(firebaseConfig)
  : null;

export const auth = firebaseApp ? getAuth(firebaseApp) : null;

export const googleProvider = new GoogleAuthProvider();

// Messaging needs everything auth needs (a real project) plus actual browser
// support: no Service Worker/Push API (older Safari), and no `navigator` at
// all when this module is evaluated outside a browser (build tooling, a
// test runner). `getMessaging` throws rather than returning null in either
// case, so this is a plain try/catch rather than the async `isSupported()`
// helper — every other export in this module is synchronous, and a hook
// reading `messaging` at module load needs a value immediately, not a
// promise to await first.
const canUseMessaging =
  typeof window !== 'undefined' &&
  typeof navigator !== 'undefined' &&
  'serviceWorker' in navigator &&
  'PushManager' in window;

let messagingInstance = null;
if (firebaseApp && canUseMessaging) {
  try {
    messagingInstance = getMessaging(firebaseApp);
  } catch {
    messagingInstance = null;
  }
}

export const messaging = messagingInstance;
