import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Check, Copy, Send } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { families as familiesApi } from "@/api/gamiraClient";
import PageHeader from "@/components/gamira/PageHeader";

const ROLES = [
  { value: "family", label: "Family member", hint: "Can view and manage day-to-day care" },
  { value: "caregiver", label: "Caregiver", hint: "Full access, like a family member" },
  { value: "doctor", label: "Doctor", hint: "Read-only" },
  { value: "viewer", label: "Viewer", hint: "Read-only" },
];

const fc =
  "w-full px-4 py-3 rounded-2xl bg-white border border-border text-[14px] focus:outline-none focus:ring-2 focus:ring-primary/30";
const lc = "block text-[12px] font-semibold text-muted-foreground mb-1.5";

export default function InviteMember() {
  const { activeFamily, seniors } = useAuth();
  const [searchParams] = useSearchParams();
  const seniorId = searchParams.get("senior") || "";
  const linkedSenior = useMemo(
    () => seniors.find((senior) => senior.id === seniorId) || null,
    [seniors, seniorId],
  );

  const [role, setRole] = useState(linkedSenior ? "viewer" : "family");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [invite, setInvite] = useState(null); // { link }
  const [copied, setCopied] = useState(false);

  const send = async () => {
    if (!activeFamily) return;
    setSending(true);
    setError("");
    try {
      const body = {
        role: linkedSenior ? "viewer" : role,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        ...(linkedSenior ? { senior_profile_id: linkedSenior.id } : {}),
      };
      const created = await familiesApi.invite(activeFamily.id, body);
      const link = `${window.location.origin}/invite/${encodeURIComponent(created.token)}`;
      setInvite({ link });
    } catch (err) {
      setError(err.message || "Could not create the invitation.");
    } finally {
      setSending(false);
    }
  };

  const copyLink = async () => {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(invite.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable; the link is still selectable on screen */
    }
  };

  return (
    <div>
      <PageHeader
        title={linkedSenior ? `Invite ${linkedSenior.preferred_name}` : "Invite someone"}
        subtitle={
          linkedSenior
            ? "They'll sign in as themselves and see their own care record"
            : "Send them a link to join this family"
        }
      />

      {error && (
        <div className="mb-4 rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {invite ? (
        <div className="rounded-[20px] bg-white border border-border p-4 space-y-3">
          <p className="text-[13px] font-semibold text-foreground">Share this link</p>
          <p className="text-[12px] text-muted-foreground break-all font-mono bg-secondary/40 rounded-xl p-3">
            {invite.link}
          </p>
          <button
            onClick={copyLink}
            className="w-full py-3 rounded-2xl border border-border text-[14px] font-semibold text-foreground flex items-center justify-center gap-2 active:scale-[0.99]"
          >
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
            {copied ? "Copied" : "Copy link"}
          </button>
          <p className="text-[11px] text-muted-foreground">
            Valid for 7 days, and works once. Anyone with this link can join —
            only send it to the person you mean to invite.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {!linkedSenior && (
            <div>
              <p className={lc}>Role</p>
              <div className="space-y-2">
                {ROLES.map((option) => (
                  <button
                    type="button"
                    key={option.value}
                    onClick={() => setRole(option.value)}
                    className={`w-full text-left px-4 py-3 rounded-2xl border transition-colors ${
                      role === option.value ? "border-primary bg-primary/5" : "border-border bg-white"
                    }`}
                  >
                    <p className="text-[14px] font-semibold text-foreground">{option.label}</p>
                    <p className="text-[12px] text-muted-foreground">{option.hint}</p>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className={lc} htmlFor="invite-email">
              Email (optional)
            </label>
            <input
              id="invite-email"
              type="email"
              className={fc}
              placeholder="name@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div>
            <label className={lc} htmlFor="invite-phone">
              Phone (optional)
            </label>
            <input
              id="invite-phone"
              type="tel"
              className={fc}
              placeholder="+91 90000 00000"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </div>

          <button
            onClick={send}
            disabled={sending}
            className="w-full py-3.5 rounded-2xl bg-primary text-primary-foreground text-[15px] font-semibold shadow-float disabled:opacity-50 flex items-center justify-center gap-2 active:scale-[0.99]"
          >
            <Send className="w-5 h-5" />
            {sending ? "Creating invitation…" : "Create invitation link"}
          </button>
        </div>
      )}
    </div>
  );
}
