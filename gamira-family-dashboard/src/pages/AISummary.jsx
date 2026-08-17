import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ClipboardList, FileText, MessageCircle, Users } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { healthApi, medicinesApi, timelineApi, toMember } from "@/api/dashboardData";
import { buildCareSummary, buildFamilySummary } from "@/lib/careSummary";
import { initialOf } from "@/lib/careStatus";
import PageHeader from "@/components/gamira/PageHeader";
import EmptyState from "@/components/gamira/EmptyState";

/**
 * Care summary.
 *
 * Named "AI Summary" in the design, and it used to call a hosted model. Every
 * line is now counted from records: how many doses were confirmed, skipped or
 * missed, which medicines are active, what the most recent readings were. A
 * family acts on this, so it has to be reproducible from the data — and
 * counting doses does not need a language model. AI narration is a later phase
 * and will sit on top of these same figures.
 */
export default function AISummary() {
  const navigate = useNavigate();
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [medicines, setMedicines] = useState([]);
  const [readings, setReadings] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!members.length) {
      setLoading(false);
      return;
    }
    try {
      const [meds, reads, timeline] = await Promise.all([
        medicinesApi.listForMembers(members),
        healthApi.listForMembers(members, { limit: 200 }),
        timelineApi.listForMembers(members, { limit: 200 }),
      ]);
      setMedicines(meds);
      setReadings(reads);
      setEvents(timeline);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberKey]);

  useEffect(() => {
    load();
  }, [load]);

  const family = useMemo(
    () => buildFamilySummary({ members, meds: medicines, events, days: 7 }),
    [members, medicines, events],
  );

  return (
    <div>
      <PageHeader title="Care Summary" subtitle="Counted from the last 7 days" backTo="/" />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-4 border-secondary border-t-primary rounded-full animate-spin"></div>
        </div>
      ) : members.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="Nothing to summarise"
          description="Add the person you care for and record a dose or a reading."
          actionLabel="Add Member"
          onAction={() => navigate("/add-member")}
        />
      ) : (
        <>
          <div className="p-5 bg-white rounded-[24px] shadow-card border border-border/50">
            <div className="flex items-center gap-2 mb-2">
              <Users className="w-5 h-5 text-primary" />
              <p className="text-[15px] font-bold text-foreground">Whole family</p>
            </div>
            <ul className="space-y-2">
              {family.lines.map((line, i) => (
                <li key={i} className="text-[13px] text-foreground leading-relaxed">
                  {line}
                </li>
              ))}
            </ul>
          </div>

          {members.map((member) => {
            const summary = buildCareSummary({
              member,
              meds: medicines.filter((m) => m.family_member_id === member.id),
              records: readings.filter((r) => r.family_member_id === member.id),
              events: events.filter((e) => e.family_member_id === member.id),
              days: 7,
            });
            return (
              <div
                key={member.id}
                className="mt-4 p-4 bg-white rounded-[20px] shadow-soft border border-border/50"
              >
                <div className="flex items-center gap-2.5 mb-2">
                  <div className="w-9 h-9 rounded-full overflow-hidden bg-secondary flex items-center justify-center shrink-0">
                    {member.photo_url ? (
                      <img src={member.photo_url} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <span className="text-[13px] font-bold text-muted-foreground">
                        {initialOf(member.name)}
                      </span>
                    )}
                  </div>
                  <p className="text-[14px] font-semibold text-foreground">{member.name}</p>
                  {member.role && <span className="text-[11px] text-muted-foreground">{member.role}</span>}
                </div>
                <ul className="space-y-1.5">
                  {summary.lines.map((line, i) => (
                    <li key={i} className="text-[13px] text-foreground leading-relaxed">
                      {line}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}

          <p className="mt-4 px-1 text-[11px] text-muted-foreground leading-relaxed">
            {family.disclaimer}
          </p>

          <div className="grid grid-cols-2 gap-2.5 mt-6">
            <Action icon={FileText} label="Report & PDF" onClick={() => navigate("/reports")} />
            <Action icon={MessageCircle} label="Ask about today" onClick={() => navigate("/ai-assistant")} />
          </div>
        </>
      )}
    </div>
  );
}

function Action({ icon: Icon, label, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center gap-1.5 py-3.5 bg-white rounded-[18px] shadow-soft border border-border/50 active:scale-[0.98]"
    >
      <Icon className="w-5 h-5 text-primary" />
      <span className="text-[12px] font-semibold text-foreground">{label}</span>
    </button>
  );
}
