import { cn } from '@/lib/utils';

export default function GamiraAvatar({ src = '', name, size = 'md' }) {
  const sizes = {
    sm: 'h-10 w-10 text-sm',
    md: 'h-12 w-12 text-base',
    lg: 'h-16 w-16 text-xl',
  };
  const initials = (name || 'G').trim().charAt(0).toUpperCase() || 'G';
  return src ? (
    <img src={src} alt={name || 'Avatar'} className={cn('rounded-full object-cover', sizes[size])} />
  ) : (
    <div className={cn('flex items-center justify-center rounded-full bg-accent/10 font-bold text-accent', sizes[size])}>
      {initials}
    </div>
  );
}
