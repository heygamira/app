// Background push handler for Firebase Cloud Messaging on the web.
//
// A file under `public/` is served exactly as written — Vite never processes
// it, so it cannot `import` anything from this app's own source, including
// the `firebase` npm package. That is why this reaches for the Firebase
// *compat* SDK from a CDN with plain `importScripts` instead of the modular
// SDK the rest of the app uses. Keep the pinned version in step with the
// `firebase` dependency in package.json.
/* eslint-disable no-undef */

importScripts('https://www.gstatic.com/firebasejs/12.17.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/12.17.1/firebase-messaging-compat.js');

// A static file can't read `import.meta.env`, so `usePushRegistration` passes
// the same public VITE_FIREBASE_* values as query params when it registers
// this worker. None of this is secret — see the comment in `src/lib/firebase.js`.
const params = new URL(self.location.href).searchParams;
const firebaseConfig = {
  apiKey: params.get('apiKey') || undefined,
  authDomain: params.get('authDomain') || undefined,
  projectId: params.get('projectId') || undefined,
  storageBucket: params.get('storageBucket') || undefined,
  messagingSenderId: params.get('messagingSenderId') || undefined,
  appId: params.get('appId') || undefined,
};

// No config (Firebase unset in this environment) or an unsupported context —
// either way, there is nothing this worker can receive.
let messaging = null;
try {
  firebase.initializeApp(firebaseConfig);
  messaging = firebase.messaging();
} catch {
  messaging = null;
}

if (messaging) {
  messaging.onBackgroundMessage((payload) => {
    const data = payload.data || {};
    const notification = payload.notification || {};
    // Plain and readable: this is read by an older person, often as a
    // lock-screen alert with no other context on screen.
    const title = notification.title || 'Gamira';
    const body = notification.body || '';

    self.registration.showNotification(title, {
      body,
      icon: '/favicon.svg',
      tag: data.notification_id || undefined,
      data,
    });
  });
}

// Route a tap to the right screen. `data` carries only structural fields —
// a notification id, a type, and sometimes an entity/senior id — never the
// content of a reading or a family note. See
// `app/services/notifications.py::_push_data` on the backend for the exact
// shape.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const data = (event.notification && event.notification.data) || {};

  let path = '/';
  if (data.type === 'medication_reminder' || data.type === 'missed_dose' || data.type === 'reminder') {
    path = '/reminders';
  } else if (data.type === 'family_update') {
    path = '/family';
  } else if (data.entity_type === 'health_reading') {
    path = '/health';
  }

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) {
          if ('navigate' in client) {
            client.navigate(path).catch(() => {});
          }
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(path);
      }
      return undefined;
    })
  );
});
