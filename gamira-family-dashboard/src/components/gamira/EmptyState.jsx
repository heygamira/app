import React from "react";

export default function EmptyState({
  icon: Icon,
  title,
  description = "",
  actionLabel = "",
  onAction = () => {},
}) {
  return (
    <div className="flex flex-col items-center text-center py-12 px-6 bg-white rounded-[24px] shadow-soft border border-border/50">
      <div className="w-16 h-16 rounded-2xl bg-secondary flex items-center justify-center">
        <Icon className="w-8 h-8 text-muted-foreground" strokeWidth={1.75} />
      </div>
      <p className="mt-3 text-[15px] font-semibold text-foreground">{title}</p>
      <p className="text-[13px] text-muted-foreground mt-1 max-w-xs">{description}</p>
      {actionLabel && (
        <button
          onClick={onAction}
          className="mt-4 px-5 py-2.5 rounded-2xl bg-primary text-primary-foreground text-[13px] font-semibold shadow-soft hover:bg-primary/90 transition-colors active:scale-[0.98]"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}