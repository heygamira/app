import React from "react";
import PageHeader from "@/components/gamira/PageHeader";
import { Heart, Users, Target } from "lucide-react";

export default function About() {
  return (
    <div>
      <PageHeader title="About Gamira" subtitle="The AI Companion for Independent Aging" backTo="/more" />

      <div className="p-5 bg-black rounded-[24px] shadow-card text-white mb-4">
        <div className="flex items-center gap-2.5 mb-2">
          <Heart className="w-6 h-6 text-white" fill="white" />
          <h2 className="text-xl font-bold">Gamira</h2>
        </div>
        <p className="text-[14px] text-white/90 leading-relaxed">
          Gamira is built to make everyday life easier for aging parents and their families.
        </p>
      </div>

      <Section
        icon={Heart}
        title="For Parents"
        tint="primary"
        iconBg="bg-primary/10"
        iconColor="text-primary"
        card="bg-primary/5"
      >
        <p>
          Gamira is a simple companion that parents can use throughout their day. They can talk to Gamira, get
          reminders for medicines and important tasks, call their family, and quickly ask for help when they need it.
        </p>
        <p>
          Everything is designed to be simple and easy to use, so parents can stay independent without feeling
          overwhelmed by technology.
        </p>
      </Section>

      <Section
        icon={Users}
        title="For Family & Admin"
        tint="success"
        iconBg="bg-success/10"
        iconColor="text-success"
        card="bg-success/5"
      >
        <p>
          The family app helps children and caregivers stay connected with their parents. It brings important
          information, reminders, schedules, health updates, and alerts into one place.
        </p>
        <p>
          Families can check in on their parents, manage their daily routines, receive important notifications, and
          stay informed without constantly having to call or ask whether everything is okay.
        </p>
      </Section>

      <Section
        icon={Target}
        title="Our Goal"
        tint="warning"
        iconBg="bg-warning/10"
        iconColor="text-warning"
        card="bg-warning/5"
      >
        <p>
          Gamira is not here to replace family. It is here to help families stay closer, even when they cannot always
          be there.
        </p>
      </Section>

      <div className="p-5 bg-gradient-gamira rounded-[24px] shadow-card text-center text-white">
        <p className="text-[15px] font-bold">Gamira, The AI Companion for Independent Aging.</p>
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, iconBg, iconColor, card, tint = "", children }) {
  return (
    <div className={`p-5 ${card} rounded-[24px] shadow-soft border border-border/40 mb-4`}>
      <div className="flex items-center gap-2.5 mb-2.5">
        <div className={`w-9 h-9 rounded-xl ${iconBg} flex items-center justify-center`}>
          <Icon className={`w-[18px] h-[18px] ${iconColor}`} strokeWidth={2} />
        </div>
        <h3 className="text-[15px] font-bold text-foreground">{title}</h3>
      </div>
      <div className="space-y-2.5 text-[13px] text-foreground/80 leading-relaxed">{children}</div>
    </div>
  );
}