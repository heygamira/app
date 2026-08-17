import React from "react";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import FamilyMemberCard from "./FamilyMemberCard";

export default function FamilySection({
  members = [],
  /** @type {(memberId: string) => string} */
  statusFor = (_memberId) => "none",
  loading = false,
}) {
  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-bold text-foreground">Your Family</h3>
        <Link to="/family" className="text-[13px] font-semibold text-primary">View All</Link>
      </div>

      {loading ? (
        <div className="flex gap-3 overflow-hidden">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-32 h-44 rounded-[20px] bg-white/60 animate-pulse shrink-0" />
          ))}
        </div>
      ) : members.length === 0 ? (
        <Link
          to="/add-member"
          className="flex flex-col items-center justify-center gap-2 p-8 bg-white rounded-[20px] border-2 border-dashed border-border"
        >
          <Plus className="w-7 h-7 text-primary" strokeWidth={2} />
          <p className="text-[14px] font-semibold text-foreground">Add your first family member</p>
        </Link>
      ) : (
        <div className="flex gap-3 overflow-x-auto overflow-y-hidden touch-pan-x no-scrollbar -mx-5 px-5 pb-2">
          {members.map((m) => (
            <Link to={`/member/${m.id}`} key={m.id} className="shrink-0 w-32">
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
            className="shrink-0 w-32 flex flex-col items-center justify-center gap-2 p-4 bg-white rounded-[20px] border-2 border-dashed border-border hover:border-primary/40 min-h-[180px]"
          >
            <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center">
              <Plus className="w-5 h-5 text-primary" strokeWidth={2.25} />
            </div>
            <p className="text-[13px] font-semibold text-foreground text-center">Add Member</p>
          </Link>
        </div>
      )}
    </section>
  );
}
