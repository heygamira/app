export default function Toggle({ checked, onChange, ariaLabel }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={() => onChange(!checked)}
      className={`flex h-9 w-16 shrink-0 items-center rounded-full p-1 transition-colors ${checked ? 'bg-primary justify-end' : 'bg-muted justify-start'}`}
    >
      <span className="h-7 w-7 rounded-full bg-white shadow" />
    </button>
  );
}
