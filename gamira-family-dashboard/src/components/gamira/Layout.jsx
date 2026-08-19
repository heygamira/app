import React, { useEffect } from "react";
import { Outlet } from "react-router-dom";
import TopNav from "./TopNav";
import BottomNav from "./BottomNav";
import SosAlertOverlay from "./SosAlertOverlay";
import DeviceNoticeBanner from "./DeviceNoticeBanner";
import { useAlerts } from "@/lib/useAlerts";
import { unlockAlarm } from "@/lib/alarm";
import { usePushRegistration } from "@/lib/usePushRegistration";

export default function Layout() {
  // One poll for both: an emergency and a flagged reading arrive down the same
  // notification list, and are told apart by what they are, not how they look.
  const { sos, notices, acknowledge, reload } = useAlerts();

  // No UI of its own: silently (re)registers this browser for push once
  // permission is already granted, and re-runs the same alert refresh a push
  // arriving in a focused tab (which FCM never routes to the background
  // handler in firebase-messaging-sw.js).
  usePushRegistration({ onForegroundMessage: reload });

  // Buy the right to make a sound at the first opportunity. A browser refuses
  // audio until the page has been interacted with, and an SOS is precisely the
  // moment nobody is going to interact first.
  useEffect(() => {
    const options = { once: true, capture: true };
    window.addEventListener("pointerdown", unlockAlarm, options);
    window.addEventListener("keydown", unlockAlarm, options);
    return () => {
      window.removeEventListener("pointerdown", unlockAlarm, options);
      window.removeEventListener("keydown", unlockAlarm, options);
    };
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <TopNav />
      <main className="mx-auto max-w-md px-5 pt-5 pb-28 min-h-[calc(100vh-4rem)]">
        <Outlet />
      </main>
      <BottomNav />
      {/* Outside <main>: these must appear on whichever screen is open. */}
      <DeviceNoticeBanner notices={notices} onAcknowledge={acknowledge} />
      <SosAlertOverlay alerts={sos} onAcknowledge={acknowledge} />
    </div>
  );
}