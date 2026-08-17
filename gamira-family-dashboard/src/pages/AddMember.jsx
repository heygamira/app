import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Check } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { membersApi, splitList, toMember } from "@/api/dashboardData";
import { initialOf } from "@/lib/careStatus";
import PageHeader from "@/components/gamira/PageHeader";

const ROLES = ["Mother", "Father", "Grandmother", "Grandfather", "Spouse", "Sibling", "Other"];
const BLOOD_GROUPS = ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];

// The backend stores an IANA zone per person and builds every dose occurrence
// in it, so this choice decides when reminders actually fire.
const TIMEZONES = [
  "Asia/Kolkata",
  "Asia/Dubai",
  "Europe/London",
  "America/New_York",
  "America/Los_Angeles",
  "Australia/Sydney",
];

const EMPTY = {
  name: "",
  role: ROLES[0],
  date_of_birth: "",
  gender: "",
  blood_group: "",
  phone: "",
  photo_url: "",
  conditions: "",
  allergies: "",
  notes: "",
  timezone: "Asia/Kolkata",
};

export default function AddMember() {
  const navigate = useNavigate();
  const { id } = useParams();
  const editing = Boolean(id);
  const { activeFamily, seniors, checkUserAuth } = useAuth();

  const existing = useMemo(
    () => (editing ? seniors.map(toMember).find((m) => m.id === id) : null),
    [editing, id, seniors],
  );

  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!existing) return;
    setForm({
      name: existing.name || "",
      role: existing.role || ROLES[0],
      date_of_birth: existing.date_of_birth || "",
      gender: existing.gender || "",
      blood_group: existing.blood_group || "",
      phone: existing.phone || "",
      photo_url: existing.photo_url || "",
      conditions: (existing.conditions || []).join(", "),
      allergies: (existing.allergies || []).join(", "),
      notes: existing.notes || "",
      timezone: existing.timezone || "Asia/Kolkata",
    });
  }, [existing]);

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const fc = "w-full px-4 py-3 rounded-2xl bg-white border border-border text-[14px] focus:outline-none focus:ring-2 focus:ring-primary/30";
  const lc = "block text-[12px] font-semibold text-muted-foreground mb-1.5";

  const save = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    const payload = {
      name: form.name.trim(),
      role: form.role,
      date_of_birth: form.date_of_birth || undefined,
      gender: form.gender,
      blood_group: form.blood_group,
      phone: form.phone,
      photo_url: form.photo_url,
      conditions: splitList(form.conditions),
      allergies: splitList(form.allergies),
      notes: form.notes,
      timezone: form.timezone,
    };
    try {
      if (editing) {
        await membersApi.update(id, payload);
        await checkUserAuth();
        navigate(`/member/${id}`);
      } else {
        if (!activeFamily) throw new Error("No family is available for this account.");
        const created = await membersApi.create(activeFamily.id, payload);
        await checkUserAuth();
        navigate(`/member/${created.id}`);
      }
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title={editing ? "Edit Member" : "Add Family Member"}
        subtitle={editing ? "Update their details" : "Add someone you care for"}
      />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label className={lc} htmlFor="name">Name</label>
          <input id="name" className={fc} placeholder="e.g. Vikram Sharma" value={form.name} onChange={(e) => set("name", e.target.value)} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={lc} htmlFor="role">Relationship</label>
            <select id="role" className={fc} value={form.role} onChange={(e) => set("role", e.target.value)}>
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={lc} htmlFor="dob">Date of birth</label>
            {/* Stored as a date, not an age: an age written down once is wrong
                a year later. */}
            <input id="dob" type="date" className={fc} value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={lc} htmlFor="gender">Gender</label>
            <select id="gender" className={fc} value={form.gender} onChange={(e) => set("gender", e.target.value)}>
              <option value="">Not stated</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div>
            <label className={lc} htmlFor="blood">Blood group</label>
            <select id="blood" className={fc} value={form.blood_group} onChange={(e) => set("blood_group", e.target.value)}>
              {BLOOD_GROUPS.map((b) => (
                <option key={b || "unknown"} value={b}>
                  {b || "Unknown"}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className={lc} htmlFor="timezone">Timezone</label>
          <select id="timezone" className={fc} value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
            {TIMEZONES.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace("_", " ")}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Dose times are read in this zone, so an 08:00 dose stays at 08:00 for
            this person wherever you are.
          </p>
        </div>

        <div className="flex flex-col items-center">
          <p className={lc}>Photo</p>
          <div className="w-24 h-24 rounded-full overflow-hidden ring-2 ring-border bg-secondary flex items-center justify-center">
            {form.photo_url ? (
              <img src={form.photo_url} alt="" className="w-full h-full object-cover" />
            ) : (
              <span className="text-[28px] font-bold text-muted-foreground">{initialOf(form.name)}</span>
            )}
          </div>
          <input
            className={`${fc} mt-3`}
            placeholder="Image URL"
            value={form.photo_url}
            onChange={(e) => set("photo_url", e.target.value)}
          />
          <p className="text-[11px] text-muted-foreground mt-2 text-center">
            Uploading a photo needs authenticated file storage, which Gamira does
            not have yet. A link works in the meantime.
          </p>
        </div>

        <div>
          <label className={lc} htmlFor="phone">Phone</label>
          <input id="phone" className={fc} value={form.phone} onChange={(e) => set("phone", e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="conditions">Conditions (comma separated)</label>
          <input id="conditions" className={fc} placeholder="Hypertension, Type 2 diabetes" value={form.conditions} onChange={(e) => set("conditions", e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="allergies">Allergies (comma separated)</label>
          <input id="allergies" className={fc} placeholder="Penicillin" value={form.allergies} onChange={(e) => set("allergies", e.target.value)} />
        </div>

        <div>
          <label className={lc} htmlFor="notes">Notes</label>
          <textarea id="notes" className={fc} rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
        </div>

        <button
          onClick={save}
          disabled={saving || !form.name.trim()}
          className="w-full py-3.5 rounded-2xl bg-primary text-primary-foreground text-[15px] font-semibold shadow-float disabled:opacity-50 flex items-center justify-center gap-2 active:scale-[0.99]"
        >
          <Check className="w-5 h-5" />
          {saving ? "Saving…" : editing ? "Save Changes" : "Add Member"}
        </button>
      </div>
    </div>
  );
}
