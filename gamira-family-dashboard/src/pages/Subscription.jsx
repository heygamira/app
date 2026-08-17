import React from "react";
import { Check, Crown } from "lucide-react";
import PageHeader from "@/components/gamira/PageHeader";

const PLANS = [
  { id: "free", name: "Free", price: "₹0", features: ["One person", "Medicines and dose times", "Care timeline"] },
  { id: "family", name: "Family", price: "—", features: ["Everyone in the family", "Reports and exports", "Push reminders"] },
  { id: "premium", name: "Premium", price: "—", features: ["Everything in Family", "Voice companion", "Priority support"] },
];

/**
 * Plans.
 *
 * The buttons here used to write `plan: "premium"` onto the user and then show
 * "Current Plan" — no payment, no entitlement, nothing enforced anywhere. That
 * is a false promise, so the plans are shown for information only until billing
 * exists.
 */
export default function Subscription() {
  return (
    <div className="space-y-5">
      <PageHeader title="Plans" subtitle="What Gamira will offer" backTo="/more" />

      <div className="p-4 rounded-[20px] bg-secondary/50 border border-border">
        <p className="text-[13px] font-semibold text-foreground">Billing is not connected</p>
        <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
          Everything in Gamira is currently available to every account. These
          plans are listed so you know what is planned; nothing here charges you
          or unlocks a feature.
        </p>
      </div>

      <div className="space-y-3">
        {PLANS.map((plan) => (
          <div
            key={plan.id}
            className="p-5 rounded-[24px] border-2 border-border bg-white shadow-soft"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {plan.id === "premium" && <Crown className="w-5 h-5 text-amber-500" />}
                <p className="text-[16px] font-bold text-foreground">{plan.name}</p>
              </div>
              <div className="text-right">
                <p className="text-xl font-bold text-foreground">{plan.price}</p>
                <p className="text-[10px] text-muted-foreground">
                  {plan.price === "—" ? "not priced yet" : "/month"}
                </p>
              </div>
            </div>
            <div className="mt-3 space-y-1.5">
              {plan.features.map((f) => (
                <div key={f} className="flex items-center gap-2">
                  <span className="w-4 h-4 rounded-full bg-success/15 flex items-center justify-center shrink-0">
                    <Check className="w-3 h-3 text-success" />
                  </span>
                  <span className="text-[12px] text-foreground">{f}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
