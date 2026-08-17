import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Activity, Plus } from "lucide-react";
import { LineChart, Line, ResponsiveContainer, Tooltip, YAxis, XAxis } from "recharts";
import { useAuth } from "@/lib/AuthContext";
import { healthApi, metricLabel, metricUnit, toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";
import MemberSelector from "@/components/gamira/MemberSelector";
import EmptyState from "@/components/gamira/EmptyState";

export default function HealthDetail() {
  const { metric } = useParams();
  const [sp, setSp] = useSearchParams();
  const { seniors, activeSeniorId, selectSenior } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);

  const memberFromUrl = sp.get("member");
  const memberId = members.find((m) => m.id === memberFromUrl)?.id || activeSeniorId || members[0]?.id;

  const [records, setRecords] = useState([]);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const unit = metricUnit(metric);
  const label = metricLabel(metric);

  const load = useCallback(async () => {
    if (!memberId) return;
    try {
      const rows = await healthApi.list(memberId, undefined, { metric, limit: 200 });
      setRecords(rows);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, [memberId, metric]);

  useEffect(() => {
    load();
  }, [load]);

  const onSelectMember = (id) => {
    selectSenior(id);
    setSp({ member: id }, { replace: true });
  };

  // Oldest → newest for the chart.
  const series = useMemo(
    () =>
      [...records]
        .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime())
        .map((r, i) => ({ i, v: Number(r.value) || 0, label: new Date(r.recorded_at).toLocaleDateString() })),
    [records],
  );

  const addReading = async () => {
    if (!value.trim() || !memberId) return;
    setSaving(true);
    try {
      await healthApi.create(memberId, { metric, value });
      setValue("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const stats = useMemo(() => {
    if (!series.length) return null;
    const values = series.map((point) => point.v);
    return {
      count: values.length,
      latest: values[values.length - 1],
      lowest: Math.min(...values),
      highest: Math.max(...values),
    };
  }, [series]);

  return (
    <div>
      <PageHeader title={label} subtitle={unit ? `Recorded in ${unit}` : undefined} backTo="/health" />

      {members.length > 1 && (
        <MemberSelector members={members} value={memberId} onChange={onSelectMember} />
      )}

      {error && (
        <div className="mt-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="p-5 bg-white rounded-[24px] shadow-card border border-border/50 mt-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[13px] font-semibold text-foreground">{label}</p>
            <p className="text-[11px] text-muted-foreground">
              {records.length} {records.length === 1 ? "reading" : "readings"}
            </p>
          </div>
          {stats && (
            <p className="text-2xl font-bold text-foreground">
              {stats.latest} <span className="text-[12px] text-muted-foreground font-normal">{unit}</span>
            </p>
          )}
        </div>

        {series.length > 1 ? (
          <div className="h-40 mt-4 -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 5, right: 12, left: 12, bottom: 0 }}>
                <YAxis hide domain={["dataMin - 4", "dataMax + 4"]} />
                <XAxis dataKey="label" hide />
                <Tooltip
                  contentStyle={{ borderRadius: 12, border: "1px solid #E5E7EB", fontSize: 12 }}
                  labelStyle={{ display: "none" }}
                  formatter={(v) => [`${v} ${unit}`, label]}
                />
                <Line type="monotone" dataKey="v" stroke="#2563EB" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-[12px] text-muted-foreground mt-4 text-center">
            Two readings are needed before a trend can be drawn.
          </p>
        )}
      </div>

      <div className="mt-4 flex items-center gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          inputMode="decimal"
          placeholder={memberId ? `Add ${label}${unit ? ` (${unit})` : ""}` : "Select a person first"}
          className="flex-1 px-4 py-3 rounded-2xl bg-white border border-border text-[14px] focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        <button
          onClick={addReading}
          disabled={saving || !value.trim() || !memberId}
          className="px-4 py-3 rounded-2xl bg-primary text-primary-foreground text-[14px] font-semibold disabled:opacity-50 flex items-center gap-1.5"
        >
          <Plus className="w-4 h-4" /> {saving ? "Saving…" : "Add"}
        </button>
      </div>
      <p className="mt-2 px-1 text-[11px] text-muted-foreground">
        The backend rejects values outside a plausible range for this metric. It
        does not judge whether a reading is healthy.
      </p>

      {stats && (
        <div className="grid grid-cols-3 gap-2.5 mt-4">
          <Stat label="Readings" value={String(stats.count)} />
          <Stat label="Lowest" value={`${stats.lowest}`} />
          <Stat label="Highest" value={`${stats.highest}`} />
        </div>
      )}

      <section className="mt-5">
        <h3 className="text-[13px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          History
        </h3>
        {records.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No readings yet"
            description={`Add the first ${label.toLowerCase()} reading above.`}
          />
        ) : (
          <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
            {records.map((r) => (
              <div key={r.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-[13px] font-semibold text-foreground">
                    {r.value} {r.unit}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {new Date(r.recorded_at).toLocaleString()}
                  </p>
                </div>
                <span className="text-[10px] text-muted-foreground capitalize">
                  {String(r.source || "").replace("_", " ")}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="p-3 bg-white rounded-[18px] shadow-soft border border-border/50 text-center">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-[16px] font-bold text-foreground mt-0.5">{value}</p>
    </div>
  );
}
