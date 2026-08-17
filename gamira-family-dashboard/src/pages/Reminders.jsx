import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Check, Clock, Pencil, Pill, Plus, SkipForward, Trash2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/lib/AuthContext";
import { useSwipeNav } from "@/lib/useSwipeNav";
import { dosesApi, remindersApi, toMember } from "@/api/dashboardData";
import { OPEN_DOSE_STATUSES } from "@/lib/careStatus";
import EmptyState from "@/components/gamira/EmptyState";
import MemberSelector from "@/components/gamira/MemberSelector";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "done", label: "Done" },
];

const doseStyles = {
  taken: "bg-success/10 text-success",
  skipped: "bg-muted text-muted-foreground",
  missed: "bg-destructive/10 text-destructive",
  late: "bg-amber-500/10 text-amber-500",
  due: "bg-primary/10 text-primary",
  reminded: "bg-primary/10 text-primary",
};

function DoseRow({ dose, onTaken, onSkipped, busy }) {
  const open = OPEN_DOSE_STATUSES.includes(dose.status);
  return (
    <div className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50">
      <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-primary/10">
        <Pill className="w-5 h-5 text-primary" strokeWidth={2} />
      </div>
      <div className="flex-1 min-w-0">
        <p
          className={`text-[14px] font-semibold leading-tight truncate ${
            dose.status === "taken" ? "text-muted-foreground line-through" : "text-foreground"
          }`}
        >
          {dose.medication_name || "Medicine"}
        </p>
        <p className="text-[11px] text-muted-foreground mt-0.5">
          {dose.scheduled_local_time} · {dose.family_member_name}
        </p>
      </div>
      <span
        className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold shrink-0 capitalize ${
          doseStyles[dose.status] || "bg-muted text-muted-foreground"
        }`}
      >
        {dose.status}
      </span>
      {open && (
        <>
          <button
            onClick={() => onTaken(dose)}
            disabled={busy}
            className="w-9 h-9 rounded-lg bg-success/10 flex items-center justify-center shrink-0 disabled:opacity-50"
            aria-label="Mark taken"
          >
            <Check className="w-4 h-4 text-success" strokeWidth={2.5} />
          </button>
          <button
            onClick={() => onSkipped(dose)}
            disabled={busy}
            className="w-9 h-9 rounded-lg bg-secondary flex items-center justify-center shrink-0 disabled:opacity-50"
            aria-label="Mark skipped"
          >
            <SkipForward className="w-4 h-4 text-muted-foreground" />
          </button>
        </>
      )}
    </div>
  );
}

function ReminderRow({ reminder, onToggle, onEdit, onRemove }) {
  const done = reminder.status === "completed";
  return (
    <div className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50">
      <button
        onClick={() => onToggle(reminder)}
        className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-colors ${
          done ? "bg-success text-white" : "bg-secondary"
        }`}
        aria-label={done ? "Mark active" : "Mark completed"}
      >
        {done ? (
          <Check className="w-5 h-5" strokeWidth={2.5} />
        ) : (
          <Clock className="w-5 h-5 text-muted-foreground" strokeWidth={2} />
        )}
      </button>
      <div className="flex-1 min-w-0">
        <p
          className={`text-[14px] font-semibold leading-tight truncate ${
            done ? "text-muted-foreground line-through" : "text-foreground"
          }`}
        >
          {reminder.title}
        </p>
        <p className="text-[11px] text-muted-foreground mt-0.5 capitalize">
          {[reminder.time, reminder.type].filter(Boolean).join(" · ")}
        </p>
      </div>
      <button
        onClick={() => onEdit(reminder)}
        className="w-8 h-8 rounded-lg bg-secondary flex items-center justify-center shrink-0"
        aria-label="Edit reminder"
      >
        <Pencil className="w-4 h-4 text-muted-foreground" />
      </button>
      <button
        onClick={() => onRemove(reminder)}
        className="w-8 h-8 rounded-lg bg-destructive/10 flex items-center justify-center shrink-0"
        aria-label="Delete reminder"
      >
        <Trash2 className="w-4 h-4 text-destructive" />
      </button>
    </div>
  );
}

export default function Reminders() {
  const navigate = useNavigate();
  const { seniors, activeSeniorId, selectSenior } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [doses, setDoses] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [dir, setDir] = useState(0);

  const load = useCallback(async () => {
    if (!members.length) {
      setLoading(false);
      return;
    }
    try {
      const [d, r] = await Promise.all([
        dosesApi.listForMembers(members),
        remindersApi.listForMembers(members),
      ]);
      setDoses(d);
      setReminders(r);
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

  const selected = members.find((m) => m.id === activeSeniorId) || members[0] || null;

  const switchMember = (d) => {
    const idx = members.findIndex((m) => m.id === selected?.id);
    if (idx < 0) return;
    const next = Math.min(members.length - 1, Math.max(0, idx + (d === -1 ? 1 : -1)));
    if (next !== idx) {
      setDir(d);
      selectSenior(members[next].id);
    }
  };
  const swipe = useSwipeNav(switchMember);

  const variants = {
    enter: (d) => ({ x: d === -1 ? 60 : -60, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (d) => ({ x: d === -1 ? -60 : 60, opacity: 0 }),
  };

  const record = async (dose, outcome) => {
    setBusyId(dose.id);
    try {
      if (outcome === "taken") await dosesApi.markTaken(dose.id);
      else await dosesApi.markSkipped(dose.id);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  };

  const toggleReminder = async (reminder) => {
    try {
      await remindersApi.update(reminder.id, {
        status: reminder.status === "completed" ? "active" : "completed",
      });
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeReminder = async (reminder) => {
    try {
      await remindersApi.remove(reminder.id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const visibleDoses = doses
    .filter((dose) => dose.family_member_id === selected?.id)
    .filter((dose) => {
      if (filter === "open") return OPEN_DOSE_STATUSES.includes(dose.status);
      if (filter === "done") return !OPEN_DOSE_STATUSES.includes(dose.status);
      return true;
    })
    .sort((a, b) => a.scheduled_local_time.localeCompare(b.scheduled_local_time));

  const visibleReminders = reminders
    .filter((reminder) => reminder.family_member_id === selected?.id)
    .filter((reminder) => {
      if (filter === "open") return reminder.status === "active";
      if (filter === "done") return reminder.status !== "active";
      return true;
    });

  const isEmpty = visibleDoses.length === 0 && visibleReminders.length === 0;

  return (
    <div className="space-y-5 select-none min-h-[calc(100vh-9rem)]" {...swipe}>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Reminders</h1>
          <p className="text-[13px] text-muted-foreground mt-0.5">Today&apos;s doses and routines</p>
        </div>
        <button
          onClick={() => navigate(selected ? `/add-reminder?member=${selected.id}` : "/add-reminder")}
          className="w-11 h-11 rounded-2xl bg-primary flex items-center justify-center shadow-float active:scale-95 transition-transform"
          aria-label="Add reminder"
        >
          <Plus className="w-5 h-5 text-white" strokeWidth={2.25} />
        </button>
      </div>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-4 py-2 rounded-full text-[13px] font-semibold transition-colors ${
              filter === f.key
                ? "bg-primary text-white"
                : "bg-white text-muted-foreground border border-border"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2.5">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-[18px] bg-white/60 animate-pulse" />
          ))}
        </div>
      ) : members.length === 0 ? (
        <EmptyState
          icon={Bell}
          title="No one added yet"
          description="Add the person you care for to start tracking their doses."
          actionLabel="Add Member"
          onAction={() => navigate("/add-member")}
        />
      ) : (
        <>
          <MemberSelector members={members} value={selected?.id} onChange={selectSenior} />
          <AnimatePresence mode="wait" custom={dir}>
            {isEmpty ? (
              <motion.div
                key={`empty-${selected?.id}`}
                custom={dir}
                variants={variants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.28, ease: "easeOut" }}
              >
                <EmptyState
                  icon={Bell}
                  title="Nothing here yet"
                  description="Doses appear once a medicine has a schedule. Tap + to add a reminder."
                  actionLabel="Add Reminder"
                  onAction={() => navigate("/add-reminder")}
                />
              </motion.div>
            ) : (
              <motion.div
                key={selected?.id}
                custom={dir}
                variants={variants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.28, ease: "easeOut" }}
                className="space-y-4"
              >
                {visibleDoses.length > 0 && (
                  <section className="space-y-2.5">
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide px-1">
                      Doses today
                    </p>
                    {visibleDoses.map((dose) => (
                      <DoseRow
                        key={dose.id}
                        dose={dose}
                        busy={busyId === dose.id}
                        onTaken={(d) => record(d, "taken")}
                        onSkipped={(d) => record(d, "skipped")}
                      />
                    ))}
                  </section>
                )}

                {visibleReminders.length > 0 && (
                  <section className="space-y-2.5">
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide px-1">
                      Reminders
                    </p>
                    {visibleReminders.map((reminder) => (
                      <ReminderRow
                        key={reminder.id}
                        reminder={reminder}
                        onToggle={toggleReminder}
                        onEdit={(r) => navigate(`/add-reminder?edit=${r.id}&member=${r.family_member_id}`)}
                        onRemove={removeReminder}
                      />
                    ))}
                  </section>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
