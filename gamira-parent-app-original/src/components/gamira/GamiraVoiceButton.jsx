import { motion } from 'framer-motion';
import { Mic, MicOff } from 'lucide-react';

/**
 * The microphone button, which is also the app's only status light.
 *
 * It used to have two appearances — the blue gradient, and the blue gradient
 * with rings — so "Gamira is asleep", "Gamira is listening for her name" and
 * "Gamira is in a conversation with you" all looked identical. On a screen
 * whose whole premise is voice, the one thing it could not tell you was
 * whether anything was listening.
 *
 * Five states now, distinguished by colour *and* by movement, because colour
 * alone fails the person this app is for:
 *
 *   off        grey, still            nothing is listening
 *   wake       grey, slow breath      listening for "Gamira", no session
 *   connecting gradient, quick pulse  opening
 *   listening  gradient, rings        in a conversation, your turn
 *   speaking   gradient, strong pulse she is talking
 *
 * Grey is deliberate for `wake`. Somebody glancing at the phone should be able
 * to see at once that no conversation is running and nothing is being sent
 * anywhere — the slow breath says it is ready, the colour says it is idle.
 *
 * @param {{state?: 'off'|'wake'|'connecting'|'listening'|'speaking'|'working',
 *          onClick?: () => void, label?: string}} props
 */
export default function GamiraVoiceButton({ state = 'off', onClick, label }) {
  const live = state === 'listening' || state === 'speaking' || state === 'working';
  const inSession = live || state === 'connecting';
  const asleep = state === 'off';

  const pulse =
    state === 'speaking'
      ? { scale: [1, 1.09, 1], duration: 1.1 }
      : state === 'connecting'
        ? { scale: [1, 1.05, 1], duration: 0.9 }
        : state === 'listening' || state === 'working'
          ? { scale: [1, 1.05, 1], duration: 1.8 }
          : state === 'wake'
            ? // A slow, shallow breath: awake, not busy. Anything livelier
              // would claim a conversation that is not happening.
              { scale: [1, 1.03, 1], duration: 3.6 }
            : { scale: 1, duration: 0 };

  return (
    <div className="relative flex flex-col items-center gap-4">
      <div className="relative flex h-32 w-32 items-center justify-center">
        <div
          className="absolute inset-0 rounded-full blur-xl transition-opacity duration-500"
          style={{
            opacity: inSession ? 0.7 : 0,
            background:
              'radial-gradient(circle, rgba(124,92,252,0.35) 0%, rgba(37,99,235,0.15) 60%, transparent 100%)',
          }}
        />
        {live && (
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
          animate={{ scale: pulse.scale }}
          transition={{
            duration: pulse.duration || 0,
            repeat: pulse.duration ? Infinity : 0,
            ease: 'easeInOut',
          }}
          whileTap={{ scale: 0.94 }}
          className={`relative z-10 flex h-24 w-24 items-center justify-center rounded-full transition-colors duration-500 ${
            inSession
              ? 'text-white'
              : 'border border-border bg-muted text-muted-foreground'
          }`}
          style={
            inSession
              ? {
                  background: 'linear-gradient(135deg, #2563EB 0%, #7C5CFC 100%)',
                  boxShadow: '0 12px 32px rgba(124,92,252,0.45)',
                }
              : undefined
          }
          aria-label={label}
        >
          {asleep ? <MicOff className="h-10 w-10" /> : <Mic className="h-10 w-10" />}
        </motion.button>
      </div>
      {label && <p className="text-[15px] font-medium text-muted-foreground">{label}</p>}
    </div>
  );
}
