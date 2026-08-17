import React from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft } from "lucide-react";

export default function PageHeader({ title, subtitle = "", backTo = "" }) {
  const navigate = useNavigate();
  return (
    <div className="flex items-center gap-2 -mt-1 mb-5">
      <button
        onClick={() => (backTo ? navigate(backTo) : navigate(-1))}
        className="w-10 h-10 -ml-2 flex items-center justify-center rounded-xl hover:bg-secondary/60 transition-colors"
      >
        <ChevronLeft className="w-5 h-5 text-foreground" strokeWidth={2.25} />
      </button>
      <div>
        <h1 className="text-xl font-bold text-foreground leading-tight">{title}</h1>
        {subtitle && <p className="text-[12px] text-muted-foreground">{subtitle}</p>}
      </div>
    </div>
  );
}