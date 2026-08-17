import { cn } from '@/lib/utils';

export default function GamiraButton({ children, className = '', variant = 'primary', ...props }) {
  const variants = {
    primary: 'bg-primary text-primary-foreground',
    secondary: 'bg-secondary text-secondary-foreground',
    outline: 'border border-border bg-card text-foreground',
    destructive: 'bg-destructive text-white',
  };
  return (
    <button
      className={cn(
        'flex h-14 min-h-[52px] w-full items-center justify-center rounded-2xl px-5 text-[15px] font-semibold transition active:scale-95',
        variants[variant],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
