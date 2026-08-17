import { motion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';

export default function SettingRow({ icon: Icon, iconBg = "", iconColor = "", title, description = null, value = null, onClick = undefined }) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileTap={{ scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 400, damping: 30 }}
      className="flex w-full items-center gap-4 rounded-2xl border border-border/60 bg-card p-4 text-left shadow-[0_2px_10px_rgba(0,0,0,0.04)] transition-colors active:bg-muted/60"
    >
      <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ${iconBg}`}>
        <Icon className={`h-6 w-6 ${iconColor}`} strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-lg font-semibold leading-tight text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {value ? (
        <span className="shrink-0 text-base font-medium text-muted-foreground">{value}</span>
      ) : null}
      <ChevronRight className="h-6 w-6 shrink-0 text-muted-foreground" strokeWidth={2} />
    </motion.button>
  );
}
