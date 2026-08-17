import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { dosesApi, toMember } from "@/api/dashboardData";
import { careStatusFor } from "@/lib/careStatus";
import FamilyMemberCard from "@/components/gamira/FamilyMemberCard";

export default function Family() {
  const { seniors, isLoadingAuth } = useAuth();
  const members = useMemo(() => seniors.map(toMember), [seniors]);
  const memberKey = members.map((m) => m.id).join(",");

  const [doses, setDoses] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!members.length) return;
    let cancelled = false;
    dosesApi
      .listForMembers(members)
      .then((rows) => {
        if (!cancelled) setDoses(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberKey]);

  const statusFor = useCallback(
    (memberId) => careStatusFor(doses.filter((dose) => dose.family_member_id === memberId)),
    [doses],
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Family</h1>
          <p className="text-[13px] text-muted-foreground mt-0.5">
            {members.length} {members.length === 1 ? "person" : "people"} in your care
          </p>
        </div>
        <Link
          to="/add-member"
          className="w-11 h-11 rounded-2xl bg-primary flex items-center justify-center shadow-float active:scale-95 transition-transform"
          aria-label="Add member"
        >
          <Plus className="w-5 h-5 text-white" strokeWidth={2.25} />
        </Link>
      </div>

      {error && (
        <div className="rounded-[18px] bg-destructive/10 p-4 text-[13px] font-medium text-destructive">
          {error}
        </div>
      )}

      {isLoadingAuth ? (
        <div className="grid grid-cols-2 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-40 rounded-[20px] bg-white/60 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {members.map((m) => (
            <Link to={`/member/${m.id}`} key={m.id}>
              <FamilyMemberCard
                name={m.name}
                role={m.role}
                photoUrl={m.photo_url}
                status={statusFor(m.id)}
              />
            </Link>
          ))}
          <Link
            to="/add-member"
            className="flex flex-col items-center justify-center gap-2 p-4 bg-white rounded-[20px] border-2 border-dashed border-border hover:border-primary/40 hover:bg-secondary/30 transition-colors min-h-[160px]"
          >
            <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center">
              <Plus className="w-5 h-5 text-primary" strokeWidth={2.25} />
            </div>
            <p className="text-[13px] font-semibold text-foreground">Add Member</p>
          </Link>
        </div>
      )}
    </div>
  );
}
