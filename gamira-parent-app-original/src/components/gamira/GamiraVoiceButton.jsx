import { motion } from 'framer-motion';
import { Mic } from 'lucide-react';

export default function GamiraVoiceButton({ listening, onClick, label }) {
  return (
    <div className="relative flex flex-col items-center gap-4">
      <div className="relative flex h-32 w-32 items-center justify-center">
        <div
          className="absolute inset-0 rounded-full opacity-70 blur-xl"
          style={{
            background:
              'radial-gradient(circle, rgba(124,92,252,0.35) 0%, rgba(37,99,235,0.15) 60%, transparent 100%)',
          }}
        />
        {listening && (
          <>
            <motion.span
              className="absolute inset-0 rounded-full border-2 border-primary/40"
              animate={{ scale: [1, 1.45], opacity: [0.6, 0] }}
              transition={{ duration: 2, repeat: Infinity, ease: 'easeOut' }}
            />
            <motion.span
              className="absolute inset-0 rounded-full border-2 border-accent/40"
              animate={{ scale: [1, 1.45], opacity: [0.6, 0] }}
              transition={{ duration: 2, repeat: Infinity, ease: 'easeOut', delay: 0.7 }}
            />
          </>
        )}
        <motion.button
          onClick={onClick}
          animate={{ scale: listening ? [1, 1.05, 1] : 1 }}
          transition={{ duration: 1.8, repeat: listening ? Infinity : 0, ease: 'easeInOut' }}
          whileTap={{ scale: 0.94 }}
          className="relative z-10 flex h-24 w-24 items-center justify-center rounded-full text-white"
          style={{
            background: 'linear-gradient(135deg, #2563EB 0%, #7C5CFC 100%)',
            boxShadow: '0 12px 32px rgba(124,92,252,0.45)',
          }}
          aria-label={label}
        >
          <Mic className="h-10 w-10" />
        </motion.button>
      </div>
      {label && <p className="text-[15px] font-medium text-muted-foreground">{label}</p>}
    </div>
  );
}
