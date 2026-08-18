// The sound an SOS makes on a family member's screen.
//
// Two things this has to survive that a one-shot beep did not:
//
//   1. **Autoplay policy.** A browser will not let a page make a noise until
//      somebody has interacted with it, and an `AudioContext` built before that
//      starts *suspended* — `start()` on it is silent, with no error. A
//      dashboard left open on a desk is exactly the case that matters, and it
//      was exactly the case that stayed quiet. So one context is created and
//      unlocked on the first interaction with the app, whenever that was, and
//      kept.
//   2. **Being missed.** One pair of tones while somebody is looking elsewhere
//      is a sound nobody hears. It repeats until the alert is acknowledged.
//
// Deliberately not the Parent App's gentle chime. That one says "I heard you";
// this one has to carry a room.

let ctx = null;
let unlocked = false;
let repeatTimer = null;

/** Build the context once, and resume it while we are allowed to. */
function audio() {
  try {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    if (!ctx) ctx = new Ctor();
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    return ctx;
  } catch {
    return null;
  }
}

/**
 * Let the alarm make a sound later.
 *
 * Call once from anywhere in the app on the first user gesture. Without this an
 * emergency arriving on an untouched tab is silent.
 */
export function unlockAlarm() {
  if (unlocked) return;
  const context = audio();
  if (!context) return;
  unlocked = true;
  // A silent blip: enough to move the context out of `suspended` inside the
  // gesture, inaudible to anybody in the room.
  try {
    const osc = context.createOscillator();
    const gain = context.createGain();
    gain.gain.value = 0.0001;
    osc.connect(gain).connect(context.destination);
    osc.start();
    osc.stop(context.currentTime + 0.01);
  } catch {
    /* nothing to do */
  }
}

/** One urgent burst: three rising tones, loud enough to turn a head. */
function burst() {
  const context = audio();
  if (!context || context.state !== "running") return;
  const now = context.currentTime;
  [0, 0.22, 0.44].forEach((offset, i) => {
    const osc = context.createOscillator();
    const gain = context.createGain();
    osc.type = "square"; // harsher than a sine on a laptop speaker
    osc.frequency.setValueAtTime(740 + i * 180, now + offset);
    gain.gain.setValueAtTime(0.0001, now + offset);
    gain.gain.exponentialRampToValueAtTime(0.22, now + offset + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.18);
    osc.connect(gain).connect(context.destination);
    osc.start(now + offset);
    osc.stop(now + offset + 0.2);
  });
}

/**
 * Sound the alarm until `stopAlarm`.
 *
 * Idempotent: calling it again while it is already running does nothing, so a
 * re-render or a second alert does not stack two alarms on top of each other.
 */
export function startAlarm(intervalMs = 3000) {
  if (repeatTimer) return;
  burst();
  repeatTimer = setInterval(burst, intervalMs);
}

export function stopAlarm() {
  if (!repeatTimer) return;
  clearInterval(repeatTimer);
  repeatTimer = null;
}

/** Whether a sound could actually be made right now. */
export function alarmAudible() {
  return Boolean(ctx && ctx.state === "running");
}
