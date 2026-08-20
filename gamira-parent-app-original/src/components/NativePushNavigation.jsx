import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { pathForPushData } from '@/lib/pushRouting';

// Native-only: routes a tapped push (foreground, backgrounded, or cold
// start) to the right screen. The web equivalent lives in
// firebase-messaging-sw.js's `notificationclick` handler.
export default function NativePushNavigation() {
  const navigate = useNavigate();

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return undefined;

    const subPromise = PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
      navigate(pathForPushData(action.notification?.data));
    });

    return () => {
      subPromise.then((sub) => sub.remove());
    };
  }, [navigate]);

  return null;
}
