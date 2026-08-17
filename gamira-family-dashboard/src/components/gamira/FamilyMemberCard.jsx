import React from "react";
import { MoreHorizontal } from "lucide-react";
import { careStatusMeta, initialOf } from "@/lib/careStatus";

export default function FamilyMemberCard({
  name,
  role = "",
  photoUrl = "",
  status = "none",
  onClick = null,
  onMenu = null,
}) {
  const meta = careStatusMeta(status);
  return (
    <div
      onClick={onClick}
      className="relative flex flex-col items-center p-4 bg-white rounded-[20px] shadow-soft border border-border/50 hover:shadow-card transition-shadow cursor-pointer h-full"
    >
      {onMenu && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onMenu();
          }}
          className="absolute top-2 right-2 w-7 h-7 flex items-center justify-center rounded-lg hover:bg-secondary/60"
        >
          <MoreHorizontal className="w-4 h-4 text-muted-foreground" strokeWidth={2} />
        </button>
      )}
      <div className="relative">
        <div className="w-16 h-16 rounded-full overflow-hidden ring-2 ring-secondary/60 shadow-soft bg-secondary flex items-center justify-center">
          {/* No stock photograph stands in for a real person: a family member
              without an uploaded picture shows their initial instead. */}
          {photoUrl ? (
            <img src={photoUrl} alt={name} className="w-full h-full object-cover" />
          ) : (
            <span className="text-[20px] font-bold text-muted-foreground">{initialOf(name)}</span>
          )}
        </div>
        <span className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full ${meta.dot}`} />
      </div>
      <p className="mt-3 text-[11px] font-medium text-muted-foreground">{role || "Family"}</p>
      <p className="text-[13px] font-semibold text-foreground leading-tight text-center">{name}</p>
      <span className={`mt-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold ${meta.pill}`}>
        {meta.label}
      </span>
    </div>
  );
}
