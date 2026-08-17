import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, ChevronRight, Globe, Info, LogOut, Moon, Pencil, Smartphone, User } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { useTheme } from "@/lib/ThemeContext";
import { initialOf } from "@/lib/careStatus";

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिन्दी" },
  { value: "mr", label: "मराठी" },
];

export default function Settings() {
  const navigate = useNavigate();
  const { user, logout, updateProfile } = useAuth();
  const { theme, toggle } = useTheme();
  const [error, setError] = useState("");

  // The theme is stored on the user so the Parent App and this dashboard agree.
  const toggleTheme = async () => {
    const next = theme === "dark" ? "light" : "dark";
    toggle();
    try {
      await updateProfile({ theme: next });
    } catch (err) {
      setError(err.message);
    }
  };

  const setLanguage = async (locale) => {
    try {
      await updateProfile({ locale });
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Settings</h1>
        <p className="text-[13px] text-muted-foreground mt-0.5">Profile and preferences</p>
      </div>

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <button
        onClick={() => navigate("/profile")}
        className="w-full flex items-center gap-3 p-4 bg-white rounded-[20px] shadow-card border border-border/50 text-left hover:bg-secondary/30 transition-colors"
      >
        <div className="w-14 h-14 rounded-full overflow-hidden ring-2 ring-secondary/60 bg-secondary flex items-center justify-center shrink-0">
          {user?.photo_url ? (
            <img src={user.photo_url} alt="" className="w-full h-full object-cover" />
          ) : (
            <span className="text-[20px] font-bold text-muted-foreground">{initialOf(user?.name)}</span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[15px] font-bold text-foreground truncate">{user?.name || "Your name"}</p>
          <p className="text-[12px] text-muted-foreground truncate">{user?.email || "No email on file"}</p>
        </div>
        <Pencil className="w-4 h-4 text-muted-foreground shrink-0" />
      </button>

      <Section title="Preferences">
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50 overflow-hidden">
          <div className="w-full flex items-center gap-3 px-4 py-3.5">
            <IconBox icon={Globe} />
            <span className="flex-1 text-left text-[14px] font-medium text-foreground">Language</span>
            <select
              value={user?.locale || "en"}
              onChange={(e) => setLanguage(e.target.value)}
              className="rounded-lg border border-border bg-background px-2 py-1 text-[13px]"
            >
              {LANGUAGES.map((lang) => (
                <option key={lang.value} value={lang.value}>
                  {lang.label}
                </option>
              ))}
            </select>
          </div>

          <div className="w-full flex items-center gap-3 px-4 py-3.5">
            <IconBox icon={Moon} />
            <span className="flex-1 text-left text-[14px] font-medium text-foreground">Dark mode</span>
            <Toggle on={theme === "dark"} onClick={toggleTheme} label="Dark mode" />
          </div>

          <div className="w-full flex items-start gap-3 px-4 py-3.5">
            <IconBox icon={Bell} />
            <div className="flex-1">
              <p className="text-[14px] font-medium text-foreground">Push notifications</p>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Not connected yet. The backend records what it would send; delivery
                to phones arrives with Firebase Cloud Messaging.
              </p>
            </div>
          </div>
        </div>
      </Section>

      <Section title="Account">
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50 overflow-hidden">
          <Row icon={User} label="Edit profile" onClick={() => navigate("/profile")} />
          <Row icon={Smartphone} label="Connected devices" onClick={() => navigate("/smart-home")} />
          <Row icon={Info} label="About Gamira" onClick={() => navigate("/about")} />
        </div>
      </Section>

      <button
        onClick={() => logout()}
        className="w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-destructive/10 text-destructive text-[14px] font-semibold"
      >
        <LogOut className="w-5 h-5" /> Sign out
      </button>
    </div>
  );
}

function IconBox({ icon: Icon }) {
  return (
    <div className="w-9 h-9 rounded-xl bg-secondary flex items-center justify-center shrink-0">
      <Icon className="w-[18px] h-[18px] text-foreground" strokeWidth={2} />
    </div>
  );
}

function Row({ icon, label, onClick }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-secondary/30 transition-colors"
    >
      <IconBox icon={icon} />
      <span className="flex-1 text-left text-[14px] font-medium text-foreground">{label}</span>
      <ChevronRight className="w-4 h-4 text-muted-foreground" />
    </button>
  );
}

function Toggle({ on, onClick, label }) {
  return (
    <button
      onClick={onClick}
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`w-12 h-7 rounded-full transition-colors relative ${on ? "bg-primary" : "bg-muted"}`}
    >
      <span
        className={`absolute top-0.5 w-6 h-6 rounded-full !bg-white shadow transition-all ${
          on ? "left-[26px]" : "left-0.5"
        }`}
      />
    </button>
  );
}

function Section({ title, children }) {
  return (
    <div>
      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1">
        {title}
      </p>
      {children}
    </div>
  );
}
