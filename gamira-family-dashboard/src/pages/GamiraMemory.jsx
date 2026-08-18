import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Brain, Loader2, Trash2 } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { ai as aiApi } from "@/api/gamiraClient";
import { toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";

/**
 * What Gamira remembers about each person, and how to make her forget.
 *
 * The same list the person sees on their own device. That is deliberate and it
 * is the point: a companion keeping notes on somebody, readable by their
 * family but not by them, would be surveillance with a friendly voice. Both
 * sides see the same rows and either side can delete any of them.
 *
 * Unlike the Parent App's version, this one shows provenance — which
 * conversation a memory came from and how sure she was — because "why does
 * Gamira think that?" is a question a family member will ask, and the answer
 * should not require reading a database.
 */

const KIND_WORDS = {
  person: "Someone in their life",
  preference: "Something they like",
  routine: "Part of their day",
  interest: "Something they enjoy",
  event: "Something coming up",
  mood: "How a conversation felt",
  concern: "Something Gamira noticed",
};

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export default function GamiraMemory() {
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [subjectId, setSubjectId] = useState(null);
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [forgetting, setForgetting] = useState(null);

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
      setMemories(await aiApi.memories(subject.id));
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

  const forget = async (id) => {
    setForgetting(id);
    try {
      await aiApi.forgetMemory(id);
      setMemories((prev) => prev.filter((memory) => memory.id !== id));
    } catch (err) {
      setError(err);
    } finally {
      setForgetting(null);
    }
  };

  return (
    <div className="pb-6">
      <PageHeader
        title="What Gamira remembers"
        subtitle="Small things she keeps between conversations"
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
        {subject ? subject.name : "This person"} sees this same list on their own
        phone and can remove anything from it. Nothing here is medical, and
        nothing here is a care record.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {!loading && error && (
        <p className="rounded-2xl border border-border bg-white p-4 text-[13px] text-muted-foreground">
          That did not load just now. Everything else on this screen still works.
        </p>
      )}

      {!loading && !error && memories.length === 0 && (
        <div className="rounded-2xl border border-border bg-white p-6 text-center">
          <Brain className="mx-auto mb-3 h-7 w-7 text-muted-foreground" />
          <p className="text-[13px] text-muted-foreground">
            Nothing yet. Gamira picks these up as they talk to her.
          </p>
        </div>
      )}

      <ul className="flex flex-col gap-3">
        {memories.map((memory) => (
          <li
            key={memory.id}
            className="rounded-2xl border border-border bg-white p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {KIND_WORDS[memory.kind] || "Something Gamira noted"}
                </p>
                <p className="mt-1 text-[15px] leading-snug text-foreground">
                  {memory.content}
                </p>
              </div>
              <button
                type="button"
                onClick={() => forget(memory.id)}
                disabled={forgetting === memory.id}
                aria-label="Forget this"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-destructive transition active:bg-destructive/10 disabled:opacity-60"
              >
                {forgetting === memory.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
              </button>
            </div>
            {/* Where it came from. "Why does Gamira think that?" has an answer. */}
            <p className="mt-2 text-[11px] text-muted-foreground">
              Noted {when(memory.created_at)}
              {memory.model ? ` · ${memory.model}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
