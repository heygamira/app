import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Merge conditional class names and let later Tailwind utilities win.
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
