import { cn } from '@/lib/utils';

export default function GamiraCard({ children, className = '', elevated = false, onClick = undefined, ...props }) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'rounded-2xl border border-border bg-card p-4 shadow-sm',
        elevated && 'bg-elevated',
        onClick && 'cursor-pointer transition active:scale-[0.99]',
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
