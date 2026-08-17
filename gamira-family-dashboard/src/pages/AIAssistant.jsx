import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Send } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { dosesApi, healthApi, medicinesApi, timelineApi, toMember } from "@/api/dashboardData";
import { OPEN_DOSE_STATUSES } from "@/lib/careStatus";
import PageHeader from "@/components/gamira/PageHeader";

const SUGGESTIONS = [
  "What is due today?",
  "What was missed?",
  "Which medicines are active?",
  "What are the latest readings?",
];

const OPENING =
  "Ask about today and I will answer from the records. I only count what has been entered — I do not interpret readings or give medical advice.";

/**
 * Ask about today.
 *
 * Designed as a chat with a hosted model. It answers from the family's own
 * records instead: a wrong answer about whether a dose was taken is not a
 * cosmetic failure, and there is no backend AI layer yet. When one exists it
 * will sit on top of these same figures, with the same permission checks.
 */
function answer(question, data) {
  const q = question.toLowerCase();
  const { doses, medicines, readings, events } = data;

  const open = doses.filter((d) => OPEN_DOSE_STATUSES.includes(d.status));
  const missed = doses.filter((d) => d.status === "missed");
  const taken = doses.filter((d) => d.status === "taken");

  if (q.includes("miss")) {
    if (!missed.length) return "No doses are recorded as missed today.";
    return `Missed today: ${missed
      .map((d) => `${d.medication_name} at ${d.scheduled_local_time} for ${d.family_member_name}`)
      .join("; ")}.`;
  }

  if (q.includes("due") || q.includes("today") || q.includes("now") || q.includes("next")) {
    const parts = [];
    parts.push(
      open.length
        ? `Still waiting: ${open
            .map((d) => `${d.medication_name} at ${d.scheduled_local_time} for ${d.family_member_name}`)
            .join("; ")}.`
        : "Nothing is waiting to be confirmed right now.",
    );
    if (taken.length) parts.push(`${taken.length} confirmed so far today.`);
    if (missed.length) parts.push(`${missed.length} missed.`);
    return parts.join(" ");
  }

  if (q.includes("medicine") || q.includes("medication") || q.includes("drug")) {
    const active = medicines.filter((m) => m.status === "active");
    if (!active.length) return "No active medicines are recorded.";
    return `Active medicines: ${active
      .map((m) => `${m.name}${m.dosage ? ` ${m.dosage}` : ""} (${m.frequency}) for ${m.family_member_name}`)
      .join("; ")}.`;
  }

  if (q.includes("reading") || q.includes("health") || q.includes("blood") || q.includes("heart")) {
    const latest = new Map();
    for (const reading of readings) {
      const key = `${reading.family_member_id}:${reading.metric}`;
      if (!latest.has(key)) latest.set(key, reading);
    }
    if (!latest.size) return "No health readings have been recorded yet.";
    return `Most recent readings: ${[...latest.values()]
      .slice(0, 6)
      .map((r) => `${r.family_member_name} ${r.label} ${r.value} ${r.unit}`)
      .join("; ")}.`;
  }

  if (q.includes("happen") || q.includes("activity") || q.includes("timeline")) {
    if (!events.length) return "Nothing has been recorded yet.";
    return `Latest entries: ${events
      .slice(0, 5)
      .map((e) => `${e.title}${e.family_member_name ? ` (${e.family_member_name})` : ""}`)
      .join("; ")}.`;
  }

  return "I can answer what is due, what was missed, which medicines are active, the latest readings, and what has happened recently. A conversational assistant needs the backend AI layer, which is not built yet.";
}

export default function AIAssistant() {
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [data, setData] = useState({ doses: [], medicines: [], readings: [], events: [] });
  const [messages, setMessages] = useState([{ role: "assistant", text: OPENING }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const endRef = useRef(null);

  const load = useCallback(async () => {
    if (!members.length) {
      setLoading(false);
      return;
    }
    try {
      const [doses, medicines, readings, events] = await Promise.all([
        dosesApi.listForMembers(members),
        medicinesApi.listForMembers(members),
        healthApi.listForMembers(members, { limit: 60 }),
        timelineApi.listForMembers(members, { limit: 30 }),
      ]);
      setData({ doses, medicines, readings, events });
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", text: `I could not load the records: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberKey]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = (text) => {
    const question = text.trim();
    if (!question || loading) return;
    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", text: question },
      { role: "assistant", text: answer(question, data) },
    ]);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-9rem)]">
      <PageHeader title="Ask about today" subtitle="Answered from your family's records" backTo="/" />

      <div className="flex-1 overflow-y-auto space-y-3 pb-4 no-scrollbar">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-[13px] leading-relaxed ${
                m.role === "user"
                  ? "bg-primary text-primary-foreground rounded-br-md"
                  : "bg-white border border-border text-foreground rounded-bl-md shadow-soft"
              }`}
            >
              {m.text}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="flex gap-2 overflow-x-auto no-scrollbar pb-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => send(s)}
            className="px-3 py-1.5 rounded-full bg-white border border-border text-[12px] font-medium text-foreground whitespace-nowrap shrink-0"
          >
            {s}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 pb-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
          placeholder={loading ? "Loading records…" : "Ask about today"}
          disabled={loading}
          className="flex-1 px-4 py-3 rounded-2xl bg-white border border-border text-[14px] focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-60"
        />
        <button
          onClick={() => send(input)}
          disabled={loading || !input.trim()}
          className="w-11 h-11 rounded-2xl bg-primary flex items-center justify-center disabled:opacity-50 shrink-0"
          aria-label="Send"
        >
          <Send className="w-5 h-5 text-white" />
        </button>
      </div>
    </div>
  );
}
