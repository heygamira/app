import React from "react";
import { Pill } from "lucide-react";

export default function MedicineCard({ medicine, onClick }) {
  const detail = [medicine.dosage, medicine.frequency].filter(Boolean).join(" · ");
  return (
    <div
      onClick={onClick}
      className="flex items-center gap-3 p-3.5 bg-white rounded-[18px] shadow-soft border border-border/50 hover:shadow-card transition-shadow cursor-pointer"
    >
      <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
        <Pill className="w-5 h-5 text-primary" strokeWidth={2} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[14px] font-semibold text-foreground truncate">{medicine.name}</p>
        <p className="text-[11px] text-muted-foreground truncate">{detail || "No dose times set"}</p>
        {medicine.family_member_name && (
          <p className="text-[10px] text-muted-foreground/80 mt-0.5">{medicine.family_member_name}</p>
        )}
      </div>
      {medicine.status && medicine.status !== "active" && (
        <span className="shrink-0 px-2 py-0.5 rounded-full bg-muted text-[10px] font-semibold text-muted-foreground capitalize">
          {medicine.status}
        </span>
      )}
    </div>
  );
}
