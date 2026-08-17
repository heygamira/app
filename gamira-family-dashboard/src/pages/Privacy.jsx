import React from "react";
import { Link } from "react-router-dom";
import { Eye, KeyRound, Lock, Server, Users } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";

const ROLE_ACCESS = {
  owner: "Sees everything in the family and can change it.",
  caregiver: "Sees everything and can record care.",
  family: "Sees everything and can record care.",
  doctor: "Reads care data. Cannot change it.",
  viewer: "Reads care data. Cannot change it, except their own doses.",
};

/**
 * Privacy.
 *
 * This page used to offer three switches — share with doctors, family health
 * data sharing, usage analytics — that wrote to fields no backend read. A
 * privacy control that does nothing is worse than none, so this states what
 * Gamira actually does and where the real control lives.
 */
export default function Privacy() {
  const { memberships, families } = useAuth();

  const familyName = (familyId) => families.find((f) => f.id === familyId)?.name || "your family";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Privacy</h1>
        <p className="text-[13px] text-muted-foreground mt-0.5">What Gamira does with your data</p>
      </div>

      <div className="flex items-center gap-3 p-4 bg-white rounded-[20px] shadow-card border border-border/50">
        <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
          <Lock className="w-6 h-6 text-primary" />
        </div>
        <div>
          <p className="text-[14px] font-semibold text-foreground">Access is decided on the server</p>
          <p className="text-[12px] text-muted-foreground">
            Every request is checked against your family membership.
          </p>
        </div>
      </div>

      <section>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          Who can see this data
        </p>
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
          {memberships.length === 0 ? (
            <p className="px-4 py-4 text-[13px] text-muted-foreground">
              You are not a member of any family yet.
            </p>
          ) : (
            memberships.map((membership) => (
              <div key={membership.id} className="flex items-start gap-3 px-4 py-3.5">
                <div className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center shrink-0">
                  <Users className="w-[18px] h-[18px] text-foreground" />
                </div>
                <div>
                  <p className="text-[14px] font-medium text-foreground">
                    {familyName(membership.family_id)} · {membership.role}
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    {ROLE_ACCESS[membership.role] || "Access is set by your role."}
                  </p>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          How it works
        </p>
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
          <Fact
            icon={Server}
            title="One backend holds the records"
            body="Care data lives in Gamira's own database. This app never holds database credentials or AI keys."
          />
          <Fact
            icon={KeyRound}
            title="Your session is a verified token"
            body="The app sends a token the backend verifies on every request. It never sends a password to a screen."
          />
          <Fact
            icon={Eye}
            title="Nothing is shared outside your family"
            body="Gamira does not sell data, and there is no third-party analytics in this app. A doctor sees data only after being invited into the family."
          />
        </div>
      </section>

      <p className="px-1 text-[11px] text-muted-foreground leading-relaxed">
        To change who can see a person&apos;s care, change their role in{" "}
        <Link to="/family" className="font-semibold text-primary">
          Family
        </Link>
        . Removing someone takes effect on the next request they make.
      </p>
    </div>
  );
}

function Fact({ icon: Icon, title, body }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3.5">
      <div className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center shrink-0">
        <Icon className="w-[18px] h-[18px] text-foreground" />
      </div>
      <div>
        <p className="text-[14px] font-medium text-foreground">{title}</p>
        <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{body}</p>
      </div>
    </div>
  );
}
