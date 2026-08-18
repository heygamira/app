// The sounds Gamira makes about listening.
//
// Synthesised rather than shipped as audio files: each one is a few oscillator
// nodes, so there is no asset to fetch and no decode to wait for. That matters
// most for the wake sound, which has to land within about 50 ms of somebody
// saying "Gamira" — it is the acknowledgement that makes the rest of the
// connection delay bearable, and a sound that arrives late is worse than none.
//
// They are all deliberately soft: sine waves, gentle attacks, nothing above
// 1 kHz held for long. This app is used by older people who often hold the
// phone close, and a sharp notification blip is startling rather than helpful.

/** @typedef {'chime' | 'ping' | 'soft' | 'off'} WakeSound */

/** @type {ReadonlyArray<{key: WakeSound, label: string, desc: string}>} */
export const WAKE_SOUNDS = [
  { key: 'chime', label: 'Chime', desc: 'A gentle rising note' },
  { key: 'ping', label: 'Ping', desc: 'A single clear note' },
  { key: 'soft', label: 'Two notes', desc: 'Quiet and low' },
  { key: 'off', label: 'Silent', desc: 'No sound, just the screen' },
];

/**
 * One note.
 *
 * `exponentialRampToValueAtTime` cannot reach zero, hence the tiny floor
 * values — ramping to a true 0 throws, and jumping to 0 clicks.
 */
function note(ctx, { at, freq, toFreq = null, duration, gain = 0.12, type = 'sine' }) {
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, at);
  if (toFreq) osc.frequency.exponentialRampToValueAtTime(toFreq, at + duration * 0.7);

  amp.gain.setValueAtTime(0.0001, at);
  amp.gain.exponentialRampToValueAtTime(gain, at + Math.min(0.03, duration * 0.2));
  amp.gain.exponentialRampToValueAtTime(0.0001, at + duration);

  osc.connect(amp);
  amp.connect(ctx.destination);
  osc.start(at);
  osc.stop(at + duration + 0.02);
}

/**
 * Play one of Gamira's sounds on an already-running context.
 *
 * Silently does nothing if the context is not running: audio needs a user
 * gesture to unlock, and failing to make a noise must never break the thing
 * the noise was about.
 *
 * @param {AudioContext | null} ctx
 * @param {'wake' | 'stopped' | 'unavailable'} event
 * @param {WakeSound} [voice] which wake sound the person chose
 */
export function playSound(ctx, event, voice = 'chime') {
  if (!ctx || ctx.state !== 'running') return;
  const t = ctx.currentTime;

  try {
    if (event === 'wake') {
      if (voice === 'off') return;
      if (voice === 'ping') {
        note(ctx, { at: t, freq: 880, duration: 0.26, gain: 0.13 });
      } else if (voice === 'soft') {
        note(ctx, { at: t, freq: 523.25, duration: 0.16, gain: 0.1 });
        note(ctx, { at: t + 0.09, freq: 784, duration: 0.2, gain: 0.1 });
      } else {
        // Rising: the universal "go ahead, I am listening".
        note(ctx, { at: t, freq: 660, toFreq: 990, duration: 0.22, gain: 0.14 });
      }
      return;
    }

    if (event === 'stopped') {
      // Falling, and quieter than the wake sound. Ending a conversation should
      // never be more attention-grabbing than starting one.
      note(ctx, { at: t, freq: 780, toFreq: 520, duration: 0.24, gain: 0.09 });
      return;
    }

    if (event === 'unavailable') {
      // Two low, flat notes. Distinct from both of the above without being an
      // alarm — nothing here is an emergency.
      note(ctx, { at: t, freq: 320, duration: 0.12, gain: 0.09 });
      note(ctx, { at: t + 0.16, freq: 320, duration: 0.12, gain: 0.09 });
    }
  } catch {
    // A sound that will not play is not worth an error.
  }
}

/**
 * Play a sound for the settings screen, which has no session running.
 *
 * Builds a context on the spot and closes it afterwards, so previewing does not
 * leave an audio context open behind the screen.
 *
 * @param {'wake' | 'stopped' | 'unavailable'} event
 * @param {WakeSound} [voice]
 */
export function previewSound(event, voice = 'chime') {
  try {
    const ctx = new AudioContext();
    const done = () => ctx.close().catch(() => {});
    ctx.resume().then(() => {
      playSound(ctx, event, voice);
      setTimeout(done, 900);
    }, done);
  } catch {
    /* no audio on this device */
  }
}
