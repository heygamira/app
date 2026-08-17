import React, { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Check, Plus, X } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { medicinesApi, toMember } from "@/api/dashboardData";
import PageHeader from "@/components/gamira/PageHeader";

// The backend stores dose times, not a free-text frequency: an occurrence has
// to be a real time in the person's timezone before a reminder can exist.
const PRESETS = [
  { label: "Once daily (morning)", times: ["08:00"] },
  { label: "Once daily (night)", times: ["21:00"] },
  { label: "Twice daily", times: ["08:00", "20:00"] },
  { label: "Three times daily", times: ["08:00", "14:00", "20:00"] },
];

export default function AddMedicine() {
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const { seniors, activeSeniorId } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);

  const [memberId, setMemberId] = useState(sp.get("member") || activeSeniorId || members[0]?.id || "");
  const [name, setName] = useState("");
  const [dosage, setDosage] = useState("");
  const [form, setForm] = useState("");
  const [instructions, setInstructions] = useState("");
  const [prescriber, setPrescriber] = useState("");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [times, setTimes] = useState(["08:00"]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const fc = "w-full px-4 py-3 rounded-2xl bg-white border border-border text-[14px] focus:outline-none focus:ring-2 focus:ring-primary/30";
  const lc = "block text-[12px] font-semibold text-muted-foreground mb-1.5";

  const setTime = (index, value) =>
    setTimes((prev) => prev.map((t, i) => (i === index ? value : t)));

  const save = async () => {
    if (!name.trim() || !memberId) return;
    setSaving(true);
    try {
      await medicinesApi.create(memberId, {
        name: name.trim(),
        dosage,
        form,
        instructions,
        prescriber,
        startDate,
        times: times.filter(Boolean),
      });
      navigate("/medication");
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader title="Add Medicine" subtitle="Name it, then set the times it is taken" />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label className={lc} htmlFor="name">Medicine name</label>
          <input id="name" className={fc} placeholder="e.g. Amlodipine" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="member">Who is it for</label>
          <select id="member" className={fc} value={memberId} onChange={(e) => setMemberId(e.target.value)}>
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
            <label className={lc} htmlFor="dosage">Strength</label>
            <input id="dosage" className={fc} placeholder="5 mg" value={dosage} onChange={(e) => setDosage(e.target.value)} />
          </div>
          <div>
            <label className={lc} htmlFor="form">Form</label>
            <input id="form" className={fc} placeholder="Tablet" value={form} onChange={(e) => setForm(e.target.value)} />
          </div>
        </div>

        <div>
          <p className={lc}>Dose times</p>
          <div className="flex flex-wrap gap-2 mb-2">
            {PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => setTimes(preset.times)}
                className="px-3 py-1.5 rounded-full bg-white border border-border text-[12px] font-medium text-muted-foreground"
              >
                {preset.label}
              </button>
            ))}
          </div>
          <div className="space-y-2">
            {times.map((time, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  type="time"
                  className={fc}
                  value={time}
                  onChange={(e) => setTime(index, e.target.value)}
                />
                {times.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setTimes((prev) => prev.filter((_, i) => i !== index))}
                    className="w-11 h-11 rounded-2xl bg-destructive/10 flex items-center justify-center shrink-0"
                    aria-label="Remove this time"
                  >
                    <X className="w-4 h-4 text-destructive" />
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setTimes((prev) => [...prev, "12:00"])}
              className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary"
            >
              <Plus className="w-4 h-4" /> Add another time
            </button>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            Times are read in the person&apos;s own timezone, so a dose stays at
            the same local hour across daylight-saving changes.
          </p>
        </div>

        <div>
          <label className={lc} htmlFor="start">Start date</label>
          <input id="start" type="date" className={fc} value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="prescriber">Prescriber</label>
          <input id="prescriber" className={fc} placeholder="Optional" value={prescriber} onChange={(e) => setPrescriber(e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="instructions">Instructions</label>
          <textarea id="instructions" className={fc} rows={2} placeholder="e.g. With water before breakfast" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        </div>

        <button
          onClick={save}
          disabled={saving || !name.trim() || !memberId}
          className="w-full py-3.5 rounded-2xl bg-primary text-primary-foreground text-[15px] font-semibold shadow-float disabled:opacity-50 flex items-center justify-center gap-2 active:scale-[0.99]"
        >
          <Check className="w-5 h-5" /> {saving ? "Saving…" : "Save Medicine"}
        </button>
      </div>
    </div>
  );
}
