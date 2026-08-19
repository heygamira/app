import { initializeApp, getApps } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';
import { getMessaging } from 'firebase/messaging';

// The web config is not a secret — it identifies the project, it doesn't
// authorize anything by itself. Safe to ship in the client bundle, unlike
// the actual secrets `.env`'s own comment warns about elsewhere in this repo.
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

// Messaging needs more than a configured project: it needs a browser that can
// hold a service worker and receive a push, which rules out Safari before 16,
// a browser with the Push API disabled, and any non-browser context. Unlike
// `getAuth`, `getMessaging` throws synchronously in those cases rather than
// returning something inert, so this is wrapped rather than assumed — a
// checkout with Firebase configured but running somewhere unsupported must
// still load the rest of the app. `usePushRegistration` treats a null value
// here as "not supported" and never calls anything else in this module.
export const messaging = (() => {
  if (!firebaseApp) return null;
  try {
    return getMessaging(firebaseApp);
  } catch {
    return null;
  }
})();
