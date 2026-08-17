export default function InfoRow({ label, value }) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-card p-4">
      <span className="text-base text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold text-foreground">{value}</span>
    </div>
  );
}
