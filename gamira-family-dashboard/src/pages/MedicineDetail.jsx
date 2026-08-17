import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Archive, Clock, Pill } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { dosesApi, medicinesApi, toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";
import EmptyState from "@/components/gamira/EmptyState";

const doseStyles = {
  taken: "bg-success",
  skipped: "bg-muted-foreground/50",
  missed: "bg-destructive",
  late: "bg-amber-500",
  due: "bg-primary",
  reminded: "bg-primary",
};

export default function MedicineDetail() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const { seniors } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);

  const [medicine, setMedicine] = useState(null);
  const [doses, setDoses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const row = await medicinesApi.get(id);
      const member = members.find((m) => m.id === row.family_member_id);
      setMedicine({ ...row, family_member_name: member?.name || "" });
      const memberId = row.family_member_id || sp.get("member");
      if (memberId) {
        const all = await dosesApi.today(memberId);
        setDoses(all.filter((dose) => dose.medication_id === row.id));
      }
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, members.length]);

  useEffect(() => {
    load();
  }, [load]);

  const archive = async () => {
    try {
      await medicinesApi.archive(id);
      navigate("/medication");
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) {
    return (
      <div className="h-64 flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-secondary border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (!medicine) {
    return (
      <div>
        <PageHeader title="Medicine" backTo="/medication" />
        <p className="text-center text-muted-foreground py-20">{error || "Not found."}</p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={medicine.name} subtitle={medicine.family_member_name} backTo="/medication" />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3 p-4 bg-white rounded-[20px] shadow-card border border-border/50">
        <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
          <Pill className="w-7 h-7 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="text-[11px] text-muted-foreground">Strength</p>
          <p className="text-[15px] font-semibold text-foreground">{medicine.dosage || "—"}</p>
          <p className="text-[11px] text-muted-foreground mt-1">{medicine.frequency}</p>
        </div>
      </div>

      {medicine.times.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {medicine.times.map((time) => (
            <span
              key={time}
              className="px-3 py-1.5 rounded-full bg-primary/10 text-[12px] font-semibold text-primary"
            >
              {time}
            </span>
          ))}
        </div>
      )}

      {medicine.instructions && (
        <div className="mt-4 p-4 bg-white rounded-[18px] shadow-soft border border-border/50">
          <p className="text-[11px] text-muted-foreground mb-1">Instructions</p>
          <p className="text-[13px] text-foreground">{medicine.instructions}</p>
        </div>
      )}

      {medicine.prescriber && (
        <div className="mt-3 p-4 bg-white rounded-[18px] shadow-soft border border-border/50">
          <p className="text-[11px] text-muted-foreground mb-1">Prescriber</p>
          <p className="text-[13px] text-foreground">{medicine.prescriber}</p>
        </div>
      )}

      <section className="mt-5">
        <h3 className="text-[13px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
          Today&apos;s doses
        </h3>
        {doses.length === 0 ? (
          <EmptyState
            icon={Clock}
            title="No doses today"
            description="Doses are generated from this medicine's schedule. Record them on the Reminders screen."
          />
        ) : (
          <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50">
            {doses.map((dose) => (
              <div key={dose.id} className="flex items-center gap-3 px-4 py-3">
                <span className={`w-2 h-2 rounded-full shrink-0 ${doseStyles[dose.status] || "bg-muted"}`} />
                <p className="flex-1 text-[13px] text-foreground">{dose.scheduled_local_time}</p>
                <span className="text-[11px] text-muted-foreground capitalize">{dose.status}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <button
        onClick={archive}
        className="mt-5 w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-destructive/10 text-destructive text-[14px] font-semibold"
      >
        <Archive className="w-5 h-5" /> Archive medicine
      </button>
      <p className="mt-2 px-1 text-[11px] text-muted-foreground">
        Archiving stops future doses. The record and its history are kept,
        because a medicine someone actually took is part of their care history.
      </p>
    </div>
  );
}
