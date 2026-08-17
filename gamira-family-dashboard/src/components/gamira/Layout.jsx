import React from "react";
import { Outlet } from "react-router-dom";
import TopNav from "./TopNav";
import BottomNav from "./BottomNav";
import SosAlertOverlay from "./SosAlertOverlay";
import DeviceNoticeBanner from "./DeviceNoticeBanner";
import { useAlerts } from "@/lib/useAlerts";

export default function Layout() {
  // One poll for both: an emergency and a flagged reading arrive down the same
  // notification list, and are told apart by what they are, not how they look.
  const { sos, notices, acknowledge } = useAlerts();

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