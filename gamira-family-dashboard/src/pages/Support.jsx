import React, { useState } from "react";
import { ChevronDown, LifeBuoy, Save } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { notesApi } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";

const FAQS = [
  {
    q: "How do I add someone to care for?",
    a: "Open Family and tap the + button. The name and their timezone are the only required details — the timezone decides when their dose reminders fall.",
  },
  {
    q: "Why does a dose appear on the Reminders screen?",
    a: "Adding a medicine with dose times creates a dose event for each time. Confirming, skipping or missing one is recorded against that event, so the same tap twice still counts once.",
  },
  {
    q: "Who can see a person's health data?",
    a: "Only members of that person's family, and what they can do depends on their role. The backend checks this on every request; the app cannot grant itself access. See Privacy for the detail.",
  },
  {
    q: "Are the summaries written by an AI?",
    a: "No. Every line in a summary is counted from records — doses confirmed, doses missed, most recent readings. Nothing is inferred or predicted.",
  },
];

export default function Support() {
  const { activeFamily, activeSeniorId } = useAuth();
  const [open, setOpen] = useState(0);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!message.trim() || !activeFamily) return;
    setSaving(true);
    try {
      await notesApi.create(activeFamily.id, {
        title: "Support request",
        content: message.trim(),
        category: "support",
        senior_profile_id: activeSeniorId || null,
      });
      setMessage("");
      setSaved(true);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Support" subtitle="Answers, and a place to write things down" backTo="/more" />

      <div className="flex items-center gap-3 p-4 bg-white rounded-[20px] shadow-card border border-border/50">
        <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
          <LifeBuoy className="w-6 h-6 text-primary" />
        </div>
        <div>
          <p className="text-[14px] font-semibold text-foreground">How Gamira works</p>
          <p className="text-[12px] text-muted-foreground">The common questions, answered honestly.</p>
        </div>
      </div>

      <section>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          Questions
        </p>
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
          {FAQS.map((faq, i) => (
            <div key={faq.q}>
              <button
                onClick={() => setOpen(open === i ? -1 : i)}
                className="w-full flex items-center justify-between px-4 py-3.5 gap-3"
                aria-expanded={open === i}
              >
                <span className="text-[13px] font-semibold text-foreground text-left flex-1">{faq.q}</span>
                <ChevronDown
                  className={`w-4 h-4 text-muted-foreground shrink-0 transition-transform ${
                    open === i ? "rotate-180" : ""
                  }`}
                />
              </button>
              {open === i && (
                <p className="px-4 pb-3.5 text-[12px] text-muted-foreground leading-relaxed">{faq.a}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          Write a note
        </p>
        <div className="p-4 bg-white rounded-[20px] shadow-soft border border-border/50 space-y-3">
          <textarea
            value={message}
            onChange={(e) => {
              setMessage(e.target.value);
              setSaved(false);
            }}
            rows={3}
            placeholder="What went wrong, or what you need"
            className="w-full px-3 py-2.5 rounded-xl bg-white border border-border text-[13px] focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          {error && <p className="text-[12px] font-medium text-destructive">{error}</p>}
          <button
            onClick={save}
            disabled={saving || !message.trim() || !activeFamily}
            className="w-full py-3 rounded-xl bg-primary text-primary-foreground text-[13px] font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Save className="w-4 h-4" /> {saving ? "Saving…" : saved ? "Saved to your family notes" : "Save note"}
          </button>
          {/* There is no support inbox behind this yet. Saying "Message Sent!"
              would leave someone waiting for a reply that cannot come. */}
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            This saves a note your family can read. Gamira has no support inbox
            yet, so nobody outside your family is notified.
          </p>
        </div>
      </section>
    </div>
  );
}
