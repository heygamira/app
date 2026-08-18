import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, MessageCircle } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { ai as aiApi } from "@/api/gamiraClient";
import { toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";
import EmptyState from "@/components/gamira/EmptyState";

/**
 * What Gamira made of the conversations she has had.
 *
 * The family sees the *notification* when she thinks somebody would like a
 * call; this is where they can see why. Without it the nudge arrives with no
 * reasoning attached, which asks a family to trust a judgement they cannot
 * inspect — and the whole point of writing the review down with its model and
 * prompt version is that it can be inspected.
 *
 * Read straight from `ai_summaries`, so what is shown here is the row that was
 * actually written and not a re-derivation of it. Every one starts unreviewed,
 * and the page says so rather than presenting an impression as a finding.
 */

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/** "How it sounded: lonely." is a line the review wrote; pull it out to a chip. */
function split(content) {
  const lines = String(content || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  let mood = "";
  const body = [];
  const points = [];
  for (const line of lines) {
    if (line.startsWith("How it sounded:")) {
      mood = line.replace("How it sounded:", "").trim().replace(/\.$/, "");
    } else if (line.startsWith("- ")) {
      points.push(line.slice(2));
    } else {
      body.push(line);
    }
  }
  return { mood, body: body.join(" "), points };
}

const MOOD_STYLES = {
  cheerful: "bg-success/10 text-success",
  content: "bg-success/10 text-success",
  lonely: "bg-primary/10 text-primary",
  flat: "bg-muted text-muted-foreground",
  anxious: "bg-warning/10 text-warning",
  unwell: "bg-warning/10 text-warning",
  unclear: "bg-muted text-muted-foreground",
};

export default function GamiraNoticed() {
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [subjectId, setSubjectId] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const subject = members.find((m) => m.id === subjectId) || members[0] || null;

  useEffect(() => {
    if (!subjectId && members.length) setSubjectId(members[0].id);
  }, [memberKey, subjectId, members]);

  const load = useCallback(async () => {
    if (!subject) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const all = await aiApi.summaries(subject.id);
      // Conversation reviews only. The weekly care summary has its own screen
      // and reads as a different kind of thing.
      setRows(all.filter((row) => row.kind === "conversation"));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [subject]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="pb-6">
      <PageHeader
        title="What Gamira noticed"
        subtitle="After each conversation, in her words"
        backTo="/more"
      />

      {members.length > 1 && (
        <div className="flex gap-2 overflow-x-auto no-scrollbar pb-3">
          {members.map((m) => (
            <button
              key={m.id}
              onClick={() => setSubjectId(m.id)}
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

      <p className="mb-4 text-[13px] leading-relaxed text-muted-foreground">
        These are impressions of how a conversation sounded, not observations
        about anybody's health. Nothing here has been checked by a person, and
        none of it is a medical record.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {!loading && error && (
        <p className="rounded-2xl border border-border bg-white p-4 text-[13px] text-muted-foreground">
          That did not load just now. Everything else still works.
        </p>
      )}

      {!loading && !error && rows.length === 0 && (
        <EmptyState
          icon={MessageCircle}
          title="Nothing yet"
          description="Gamira writes one of these after a conversation long enough to be worth reading."
        />
      )}

      <div className="flex flex-col gap-3">
        {rows.map((row) => {
          const { mood, body, points } = split(row.content);
          return (
            <article
              key={row.id}
              className="rounded-2xl border border-border bg-white p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {when(row.generated_at || row.created_at)}
                  {row.facts?.turns ? ` · ${row.facts.turns} turns` : ""}
                </p>
                {mood && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-semibold capitalize ${
                      MOOD_STYLES[mood] || "bg-muted text-muted-foreground"
                    }`}
                  >
                    {mood}
                  </span>
                )}
              </div>

              {body && (
                <p className="mt-2 text-[14px] leading-snug text-foreground">{body}</p>
              )}

              {points.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1">
                  {points.map((point) => (
                    <li key={point} className="text-[13px] text-muted-foreground">
                      · {point}
                    </li>
                  ))}
                </ul>
              )}

              {/* Where it came from. "Why does Gamira think that?" has an answer. */}
              <p className="mt-3 text-[11px] text-muted-foreground">
                {row.model || "unknown model"}
                {row.prompt_version ? ` · ${row.prompt_version}` : ""}
                {" · unreviewed"}
              </p>
            </article>
          );
        })}
      </div>
    </div>
  );
}
