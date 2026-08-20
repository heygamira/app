// Where a tapped push notification should open the app to, native Android
// side. Mirrors `public/firebase-messaging-sw.js`'s `notificationclick`
// mapping exactly — that file is a raw `public/` asset Vite never processes,
// so it can't import this module. Keep the two in sync by hand.
export function pathForPushData(data = {}) {
  if (data.type === 'medication_reminder' || data.type === 'missed_dose' || data.type === 'reminder') {
    return '/reminders';
  }
  if (data.type === 'family_update') {
    return '/family';
  }
  if (data.entity_type === 'health_reading') {
    return '/health';
  }
  return '/';
}

export default pathForPushData;
