import React, { useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Capacitor } from "@capacitor/core";
import { App as CapacitorApp } from "@capacitor/app";
import TopNav from "./TopNav";
import BottomNav from "./BottomNav";
import SosAlertOverlay from "./SosAlertOverlay";
import DeviceNoticeBanner from "./DeviceNoticeBanner";
import OfflineBanner from "./OfflineBanner";
import { useAlerts } from "@/lib/useAlerts";
import { unlockAlarm } from "@/lib/alarm";
import { usePushRegistration } from "@/lib/usePushRegistration";

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();

  // One poll for both: an emergency and a flagged reading arrive down the same
  // notification list, and are told apart by what they are, not how they look.
  const { sos, notices, acknowledge, reload } = useAlerts();

  // No UI of its own: silently (re)registers this device for push once
  // permission is already granted, and re-runs the same alert refresh a push
  // arriving in a focused tab (which FCM never routes to the background
  // handler in firebase-messaging-sw.js).
  const push = usePushRegistration({ onForegroundMessage: reload });

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

  // Native only: hardware back button and app-lifecycle handling. Capacitor's
  // default WebView-history back behavior doesn't track React Router's own
  // stack, so this drives it explicitly instead. Resuming also reloads alerts
  // and silently re-registers push — the fast path for SosAlertActivity's
  // "Open Gamira" button (android/.../push/SosAlertActivity), which brings
  // this app forward but has no way to refresh its data itself, and a general
  // safety net for any other native alert channel.
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return undefined;

    const stateListener = CapacitorApp.addListener("appStateChange", ({ isActive }) => {
      if (isActive) {
        reload();
        push.refresh();
      }
    });

    const backListener = CapacitorApp.addListener("backButton", ({ canGoBack }) => {
      if (canGoBack && location.pathname !== "/") {
        navigate(-1);
      } else {
        CapacitorApp.exitApp();
      }
    });

    return () => {
      stateListener.then((l) => l.remove());
      backListener.then((l) => l.remove());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  return (
    <div className="min-h-screen bg-background">
      <TopNav />
      <main className="mx-auto max-w-md px-5 pt-5 pb-28 min-h-[calc(100dvh-4rem)]">
        <Outlet />
      </main>
      <BottomNav />
      {/* Outside <main>: these must appear on whichever screen is open. */}
      <DeviceNoticeBanner notices={notices} onAcknowledge={acknowledge} />
      <OfflineBanner />
      <SosAlertOverlay alerts={sos} onAcknowledge={acknowledge} />
    </div>
  );
}