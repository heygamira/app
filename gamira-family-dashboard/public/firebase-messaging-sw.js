// FCM's documented background-message handler for the web.
//
// This is a plain script, not a module: a service worker registered from a
// static file in `public/` cannot use bare ESM imports from `node_modules`,
// so it loads the Firebase **compat** build from Google's CDN instead of the
// modular SDK the rest of this app uses. Pinned to the exact `firebase`
// version in package.json so the two never drift apart.
importScripts('https://www.gstatic.com/firebasejs/12.17.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/12.17.1/firebase-messaging-compat.js');

// A service worker has no `import.meta.env` — Vite doesn't process this
// file. The page passes the real Firebase web config as query params when it
// registers this worker (see `src/lib/usePushRegistration.js`), and this
// reads them back out here.
const params = new URLSearchParams(self.location.search);
const firebaseConfig = {
  apiKey: params.get('apiKey'),
  authDomain: params.get('authDomain'),
  projectId: params.get('projectId'),
  storageBucket: params.get('storageBucket'),
  messagingSenderId: params.get('messagingSenderId'),
  appId: params.get('appId'),
};

firebase.initializeApp(firebaseConfig);

// The browser can (re)install this worker with no query string at all — for
// instance a request for `/firebase-messaging-sw.js` that isn't the page's
// own registration call — and `firebase.messaging()` would otherwise throw
// during install and permanently break the worker.
if (firebaseConfig.apiKey && firebaseConfig.projectId) {
  const messaging = firebase.messaging();

  messaging.onBackgroundMessage((payload) => {
    const data = payload.data || {};
    const title = (payload.notification && payload.notification.title) || 'Gamira';
    const body = (payload.notification && payload.notification.body) || '';

    self.registration.showNotification(title, {
      body,
      icon: '/favicon.svg',
      // Lets a newer notification about the same thing replace an unread one
      // on the lock screen instead of piling up.
      tag: data.notification_id || undefined,
      data,
    });
  });
}

// Real fields the backend actually sends in `payload.data` — see
// `gamira-backend/app/services/notifications.py` `_push_data`:
// `notification_id`, `type`, `entity_type`, `entity_id`, `senior_profile_id`.
// There is no per-entity-type deep link in this app yet, so every push opens
// the Notifications list — the one screen guaranteed to show what this was
// about — rather than guessing a route from a field that isn't a route.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetPath = '/notifications';

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientsList) => {
        const existing = clientsList.find(
          (client) => new URL(client.url).origin === self.location.origin
        );
        if (existing) {
          if ('navigate' in existing) {
            // Some browsers don't support navigating an existing client, or
            // reject it for a cross-origin/opaque URL. Either way this is a
            // convenience, not the point — focusing the tab still succeeds.
            existing.navigate(targetPath).catch(() => {});
          }
          return existing.focus();
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetPath);
        }
        return undefined;
      })
  );
});
