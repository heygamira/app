import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Send } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { ai as aiApi } from "@/api/gamiraClient";
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
 * Answer from the loaded records, without a model.
 *
 * This is the fallback, not the main path — `POST /ai/chat` is. It exists
 * because a wrong answer about whether a dose was taken is not a cosmetic
 * failure: when the assistant is unavailable this screen still says what is
 * due and what was missed, from the same figures the model would have been
 * given, and says plainly that it is doing so.
 */
function answerFromRecords(question, data) {
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

  return "I can answer what is due, what was missed, which medicines are active, the latest readings, and what has happened recently.";
}

export default function AIAssistant() {
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [data, setData] = useState({ doses: [], medicines: [], readings: [], events: [] });
  const [messages, setMessages] = useState([{ role: "assistant", text: OPENING }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [thinking, setThinking] = useState(false);
  // The backend scopes a conversation to one person and checks every answer
  // against that membership, so the question has to be about somebody in
  // particular rather than about the family in general.
  const [subjectId, setSubjectId] = useState(null);
  // Threading. Passing this back lets the model see what was already asked.
  const conversationRef = useRef(null);
  const endRef = useRef(null);

  const subject = members.find((m) => m.id === subjectId) || members[0] || null;

  useEffect(() => {
    if (!subjectId && members.length) setSubjectId(members[0].id);
  }, [memberKey, subjectId, members]);

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

  const send = async (text) => {
    const question = text.trim();
    if (!question || loading || thinking) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);

    if (!subject) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "There is nobody in this family to answer about yet." },
      ]);
      return;
    }

    setThinking(true);
    try {
      const response = await aiApi.chat({
        seniorId: subject.id,
        message: question,
        conversationId: conversationRef.current,
      });
      conversationRef.current = response.conversation_id;
      setMessages((prev) => [...prev, { role: "assistant", text: response.reply }]);
    } catch (err) {
      // The assistant being down must not take the screen with it. Answer from
      // the records that are already loaded, and say that is what happened —
      // quietly degrading would leave somebody unsure which they had read.
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: answerFromRecords(question, data),
          note:
            err.code === "network_unavailable"
              ? "Answered from the records on this device — Gamira could not be reached."
              : "Answered from the records — the assistant is unavailable right now.",
        },
      ]);
    } finally {
      setThinking(false);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-9rem)]">
      <PageHeader title="Ask about today" subtitle="Answered from your family's records" backTo="/" />

      {members.length > 1 && (
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-3">
          {members.map((m) => (
            <button
              key={m.id}
              onClick={() => {
                setSubjectId(m.id);
                // A new subject is a new conversation: the backend scopes every
                // answer to one person's record and must not be handed a thread
                // that was about somebody else.
                conversationRef.current = null;
              }}
              className={`px-3 py-1.5 rounded-full border text-[12px] font-medium whitespace-nowrap shrink-0 ${
                subject?.id === m.id
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-white text-foreground border-border"
              }`}
            >
              {m.name}
            </button>
          ))}
        </div>
      )}

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
              {m.note && (
                <p className="mt-1.5 pt-1.5 border-t border-border text-[11px] text-muted-foreground">
                  {m.note}
                </p>
              )}
            </div>
          </div>
        ))}
        {thinking && (
          <div className="flex justify-start">
            <div className="px-4 py-2.5 rounded-2xl rounded-bl-md bg-white border border-border shadow-soft">
              <span className="flex gap-1" aria-label="Gamira is answering">
                {[0, 1, 2].map((d) => (
                  <span
                    key={d}
                    className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce"
                    style={{ animationDelay: `${d * 0.15}s` }}
                  />
                ))}
              </span>
            </div>
          </div>
        )}
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
          placeholder={
            loading
              ? "Loading records…"
              : subject && members.length > 1
                ? `Ask about ${subject.name}`
                : "Ask about today"
          }
          disabled={loading}
          className="flex-1 px-4 py-3 rounded-2xl bg-white border border-border text-[14px] focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-60"
        />
        <button
          onClick={() => send(input)}
          disabled={loading || thinking || !input.trim()}
          className="w-11 h-11 rounded-2xl bg-primary flex items-center justify-center disabled:opacity-50 shrink-0"
          aria-label="Send"
        >
          <Send className="w-5 h-5 text-white" />
        </button>
      </div>
    </div>
  );
}
