import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Save } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { initialOf } from "@/lib/careStatus";
import PageHeader from "@/components/gamira/PageHeader";

export default function EditProfile() {
  const navigate = useNavigate();
  const { user, updateProfile } = useAuth();

  const [form, setForm] = useState({ display_name: "", avatar_url: "", timezone: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    setForm({
      display_name: user.display_name || "",
      avatar_url: user.avatar_url || "",
      timezone: user.timezone || "",
    });
  }, [user]);

  const save = async () => {
    setSaving(true);
    try {
      await updateProfile({
        display_name: form.display_name,
        avatar_url: form.avatar_url || null,
        timezone: form.timezone || undefined,
      });
      navigate("/settings");
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  const input =
    "w-full bg-white rounded-2xl border border-border/50 shadow-soft px-4 py-3 text-[14px] text-foreground outline-none focus:ring-2 focus:ring-primary/40";

  return (
    <div>
      <PageHeader title="Edit Profile" subtitle="Your own account details" backTo="/settings" />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="flex flex-col items-center mb-6">
        <div className="w-24 h-24 rounded-full overflow-hidden ring-4 ring-secondary/60 bg-secondary flex items-center justify-center">
          {form.avatar_url ? (
            <img src={form.avatar_url} alt="" className="w-full h-full object-cover" />
          ) : (
            <span className="text-[30px] font-bold text-muted-foreground">
              {initialOf(form.display_name || user?.email)}
            </span>
          )}
        </div>
        <p className="text-[12px] text-muted-foreground mt-3 text-center max-w-xs">
          Photo upload needs authenticated file storage, which Gamira does not
          have yet. A link works in the meantime.
        </p>
      </div>

      <div className="space-y-4">
        <Field label="Display name">
          <input
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            placeholder="Your name"
            className={input}
          />
        </Field>

        <Field label="Photo URL">
          <input
            value={form.avatar_url}
            onChange={(e) => setForm({ ...form, avatar_url: e.target.value })}
            placeholder="https://…"
            className={input}
          />
        </Field>

        <Field label="Email">
          <input
            value={user?.email || "Not provided by your sign-in method"}
            disabled
            className="w-full bg-muted rounded-2xl border border-border/50 px-4 py-3 text-[14px] text-muted-foreground cursor-not-allowed"
          />
        </Field>

        <Field label="Phone">
          <input
            value={user?.phone || "Not provided by your sign-in method"}
            disabled
            className="w-full bg-muted rounded-2xl border border-border/50 px-4 py-3 text-[14px] text-muted-foreground cursor-not-allowed"
          />
        </Field>

        <Field label="Your timezone">
          <input
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            placeholder="Asia/Kolkata"
            className={input}
          />
          <p className="text-[11px] text-muted-foreground mt-1.5 px-1">
            This is your own zone for reading times. Each person you care for
            keeps their own, which is what dose times are scheduled in.
          </p>
        </Field>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="w-full mt-6 flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-primary text-primary-foreground text-[15px] font-semibold shadow-float disabled:opacity-50 active:scale-[0.99] transition-transform"
      >
        <Save className="w-5 h-5" />
        {saving ? "Saving…" : "Save Changes"}
      </button>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <p className="text-[12px] font-semibold text-muted-foreground mb-1.5 px-1">{label}</p>
      {children}
    </div>
  );
}
