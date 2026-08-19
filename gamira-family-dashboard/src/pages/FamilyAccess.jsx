import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Send, Trash2, UserPlus } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { families as familiesApi } from "@/api/gamiraClient";
import PageHeader from "@/components/gamira/PageHeader";
import { initialOf } from "@/lib/careStatus";

const ROLE_LABELS = {
  owner: "Owner",
  family: "Family member",
  caregiver: "Caregiver",
  doctor: "Doctor",
  viewer: "Viewer",
};

export default function FamilyAccess() {
  const { activeFamily, user, memberships, seniors } = useAuth();
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState("");

  const myMembership = useMemo(
    () => memberships.find((m) => m.family_id === activeFamily?.id),
    [memberships, activeFamily],
  );
  const isOwner = myMembership?.role === "owner";

  const load = useCallback(() => {
    if (!activeFamily) return;
    setLoading(true);
    familiesApi
      .members(activeFamily.id)
      .then(setMembers)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [activeFamily]);

  useEffect(load, [load]);

  const unlinkedSeniors = useMemo(() => seniors.filter((s) => !s.user_id), [seniors]);

  const remove = async (membershipId) => {
    if (!activeFamily) return;
    setRemoving(membershipId);
    try {
      await familiesApi.removeMember(activeFamily.id, membershipId);
      setMembers((prev) => prev.filter((m) => m.id !== membershipId));
    } catch (err) {
      setError(err.message);
    } finally {
      setRemoving("");
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Family access"
        subtitle={activeFamily ? activeFamily.name : "Who can see this family's records"}
      />

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-[13px] font-semibold text-foreground">People with access</p>
        <Link
          to="/invite-member"
          className="inline-flex items-center gap-1.5 rounded-full bg-primary px-3.5 py-2 text-[12px] font-semibold text-primary-foreground active:scale-95 transition-transform"
        >
          <Send className="w-3.5 h-3.5" /> Invite
        </Link>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-[18px] bg-white/60 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50 overflow-hidden">
          {members.map((member) => (
            <div key={member.id} className="flex items-center gap-3 px-4 py-3.5">
              <div className="w-9 h-9 rounded-full bg-secondary flex items-center justify-center shrink-0">
                {member.avatar_url ? (
                  <img src={member.avatar_url} alt="" className="w-full h-full rounded-full object-cover" />
                ) : (
                  <span className="text-[13px] font-bold text-muted-foreground">
                    {initialOf(member.display_name)}
                  </span>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[14px] font-semibold text-foreground truncate">
                  {member.display_name || member.email || "Pending"}
                  {member.user_id === user?.id && (
                    <span className="text-muted-foreground font-normal"> (you)</span>
                  )}
                </p>
                <p className="text-[12px] text-muted-foreground">
                  {ROLE_LABELS[member.role] || member.role}
                </p>
              </div>
              {isOwner && member.role !== "owner" && member.user_id !== user?.id && (
                <button
                  onClick={() => remove(member.id)}
                  disabled={removing === member.id}
                  className="w-9 h-9 rounded-xl flex items-center justify-center text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
                  aria-label={`Remove ${member.display_name}`}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {unlinkedSeniors.length > 0 && (
        <div>
          <p className="text-[13px] font-semibold text-foreground mb-2">
            Cared-for people without their own sign-in
          </p>
          <div className="bg-white rounded-[20px] shadow-soft border border-border/50 divide-y divide-border/50 overflow-hidden">
            {unlinkedSeniors.map((senior) => (
              <div key={senior.id} className="flex items-center gap-3 px-4 py-3.5">
                <div className="w-9 h-9 rounded-full bg-secondary flex items-center justify-center shrink-0">
                  <span className="text-[13px] font-bold text-muted-foreground">
                    {initialOf(senior.preferred_name)}
                  </span>
                </div>
                <p className="flex-1 min-w-0 text-[14px] font-semibold text-foreground truncate">
                  {senior.preferred_name}
                </p>
                <Link
                  to={`/invite-member?senior=${senior.id}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground active:scale-95 transition-transform"
                >
                  <UserPlus className="w-3.5 h-3.5" /> Invite to sign in
                </Link>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground mt-2 px-1">
            Until this happens, they can only be seen through this dashboard —
            they can't sign in to the Parent App as themselves.
          </p>
        </div>
      )}
    </div>
  );
}
