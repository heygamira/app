import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Check, Trash2 } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { remindersApi, toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";

// The backend's ReminderType values.
const TYPES = ["medication", "appointment", "activity", "hydration", "meal", "other"];

// ISO weekday numbers, which is what the backend parses.
const DAYS = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 7, label: "Sun" },
];

export default function AddReminder() {
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const editId = sp.get("edit");
  const { seniors, activeSeniorId } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);

  const [memberId, setMemberId] = useState(
    sp.get("member") || activeSeniorId || members[0]?.id || "",
  );
  const [title, setTitle] = useState("");
  const [type, setType] = useState("medication");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [days, setDays] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // There is no single-reminder endpoint: reminders are always read through the
  // person they belong to, which is also what authorises the read.
  const loadForEdit = useCallback(async () => {
    if (!editId || !memberId) return;
    try {
      const rows = await remindersApi.list(memberId);
      const found = rows.find((row) => row.id === editId);
      if (!found) return;
      setTitle(found.title);
      setType(found.type);
      setInstructions(found.instructions || "");
      setTime(found.time || "09:00");
      setDays(found.days_of_week ? found.days_of_week.split(",").map(Number) : []);
    } catch (err) {
      setError(err.message);
    }
  }, [editId, memberId]);

  useEffect(() => {
    loadForEdit();
  }, [loadForEdit]);

  const toggleDay = (value) =>
    setDays((prev) => (prev.includes(value) ? prev.filter((d) => d !== value) : [...prev, value]));

  const fc = "w-full px-4 py-3 rounded-2xl bg-white border border-border text-[14px] text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all";
  const lc = "block text-[12px] font-semibold text-muted-foreground mb-1.5";

  const save = async () => {
    if (!title.trim() || !memberId) return;
    setSaving(true);
    const daysOfWeek = [...days].sort().join(",");
    try {
      if (editId) {
        await remindersApi.update(editId, {
          title: title.trim(),
          type,
          instructions: instructions || null,
          local_time: time || null,
          days_of_week: daysOfWeek,
        });
      } else {
        await remindersApi.create(memberId, {
          title: title.trim(),
          type,
          instructions,
          time,
          daysOfWeek,
        });
      }
      navigate("/reminders");
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!editId) return;
    try {
      await remindersApi.remove(editId);
      navigate("/reminders");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div>
      <PageHeader
        title={editId ? "Edit Reminder" : "Add Reminder"}
        subtitle={editId ? "Update or delete this reminder" : "A routine that is not a medicine dose"}
        backTo="/reminders"
      />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label className={lc} htmlFor="title">Title</label>
          <input id="title" className={fc} placeholder="e.g. Evening walk" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="member">Who is it for</label>
          <select
            id="member"
            className={fc}
            value={memberId}
            disabled={Boolean(editId)}
            onChange={(e) => setMemberId(e.target.value)}
          >
            <option value="">Select a person</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
                {m.role ? ` (${m.role})` : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={lc} htmlFor="type">Type</label>
            <select id="type" className={fc} value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={lc} htmlFor="time">Time</label>
            <input id="time" type="time" className={fc} value={time} onChange={(e) => setTime(e.target.value)} />
          </div>
        </div>

        <div>
          <p className={lc}>Repeats on</p>
          <div className="flex gap-1.5">
            {DAYS.map((day) => {
              const on = days.includes(day.value);
              return (
                <button
                  key={day.value}
                  type="button"
                  onClick={() => toggleDay(day.value)}
                  className={`flex-1 py-2 rounded-xl text-[12px] font-semibold transition-colors ${
                    on ? "bg-primary text-primary-foreground" : "bg-white border border-border text-muted-foreground"
                  }`}
                >
                  {day.label}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Selecting no day means every day.
          </p>
        </div>

        <div>
          <label className={lc} htmlFor="instructions">Notes</label>
          <textarea id="instructions" className={fc} rows={2} placeholder="Optional" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </div>

        <div className="p-4 bg-white rounded-2xl border border-border">
          <p className="text-[13px] font-semibold text-foreground">Medicines are separate</p>
          <p className="text-[12px] text-muted-foreground mt-0.5">
            A medicine and its dose times live under Medication, so each dose can
            be confirmed, skipped or marked missed on its own.
          </p>
        </div>

        <button
          onClick={save}
          disabled={saving || !title.trim() || !memberId}
          className="w-full py-3.5 rounded-2xl bg-primary text-primary-foreground text-[15px] font-semibold shadow-float disabled:opacity-50 flex items-center justify-center gap-2 hover:bg-primary/90 active:scale-[0.99]"
        >
          <Check className="w-5 h-5" /> {saving ? "Saving…" : editId ? "Save Changes" : "Save Reminder"}
        </button>

        {editId && (
          <button
            onClick={remove}
            className="w-full py-3.5 rounded-2xl bg-destructive/10 text-destructive text-[14px] font-semibold flex items-center justify-center gap-2"
          >
            <Trash2 className="w-5 h-5" /> Delete Reminder
          </button>
        )}
      </div>
    </div>
  );
}
