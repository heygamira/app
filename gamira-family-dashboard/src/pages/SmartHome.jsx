import React from "react";
import { AirVent, Camera, Lightbulb, Lock, Tv, Wifi, Wind } from "lucide-react";
import PageHeader from "@/components/gamira/PageHeader";

const PLANNED = [
  { name: "Lights", icon: Lightbulb },
  { name: "Air conditioner", icon: AirVent },
  { name: "Television", icon: Tv },
  { name: "Door lock", icon: Lock },
  { name: "Security camera", icon: Camera },
  { name: "Curtains", icon: Wind },
];

/**
 * Smart home.
 *
 * The switches here used to move and light up while controlling nothing. A door
 * lock that shows "locked" without being connected to a lock is the worst
 * possible version of that, so this screen now says plainly that nothing is
 * paired.
 */
export default function SmartHome() {
  return (
    <div className="space-y-6">
      <PageHeader title="Smart Home" subtitle="Not connected yet" backTo="/more" />

      <div className="p-4 rounded-[20px] bg-secondary/50 border border-border flex items-start gap-3">
        <Wifi className="w-5 h-5 text-muted-foreground shrink-0 mt-0.5" />
        <div>
          <p className="text-[13px] font-semibold text-foreground">No devices are paired</p>
          <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
            Gamira cannot control anything in the home yet. When device pairing
            arrives, only devices you have actually connected will appear here —
            and a control shown as on will mean it is on.
          </p>
        </div>
      </div>

      <section>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          Planned
        </p>
        <div className="grid grid-cols-2 gap-3">
          {PLANNED.map((device) => {
            const Icon = device.icon;
            return (
              <div
                key={device.name}
                className="p-4 bg-white rounded-[20px] shadow-soft border border-border/50 opacity-70"
              >
                <div className="w-10 h-10 rounded-2xl bg-muted flex items-center justify-center">
                  <Icon className="w-5 h-5 text-muted-foreground" />
                </div>
                <p className="text-[13px] font-semibold text-foreground mt-3">{device.name}</p>
                <p className="text-[11px] text-muted-foreground">Not connected</p>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
