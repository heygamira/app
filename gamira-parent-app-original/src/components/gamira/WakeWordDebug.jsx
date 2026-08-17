/**
 * Live wake-word telemetry, behind `?wake=debug`.
 *
 * The model is still being retrained, and the number that matters is not the
 * one from the offline sweep — it is how it behaves on the actual phone, in the
 * actual room, through the browser's own noise suppression and gain control.
 * This is the instrument for that: arm the app, say the word a dozen times,
 * watch where the score peaks and how often it fires when nobody spoke.
 *
 * Never rendered without the query parameter, so it costs nothing in normal use.
 */
export default function WakeWordDebug({ wake }) {
  const t = wake.telemetry;
  if (!t) {
    return (
      <div className="fixed bottom-2 left-2 right-2 z-50 rounded-lg bg-black/85 p-2 font-mono text-[11px] text-emerald-300">
        wake: {wake.engine} {wake.armed ? '(starting…)' : '(not armed — tap the mic)'}
        {wake.error ? ` — ${wake.error.message}` : ''}
      </div>
    );
  }

  const pct = (v) => `${Math.round((v ?? 0) * 100)}`.padStart(3);
  const bar = (value, threshold) => {
    const width = 28;
    const filled = Math.min(width, Math.round((value ?? 0) * width));
    const mark = Math.min(width - 1, Math.round((threshold ?? 1) * width));
    return Array.from({ length: width }, (_, i) => {
      if (i === mark) return '|';
      return i < filled ? '#' : '.';
    }).join('');
  };

  const row = (label, value) => (
    <div className="flex gap-2">
      <span className="w-[4.5rem] shrink-0 text-emerald-500/70">{label}</span>
      <span className="truncate">{value}</span>
    </div>
  );

  return (
    <div className="fixed bottom-2 left-2 right-2 z-50 rounded-lg bg-black/85 p-2 font-mono text-[11px] leading-tight text-emerald-300">
      {row('engine', `${wake.engine} ${t.version || ''} ${t.resampling ? `resampled from ${t.resampling}Hz` : ''}`)}
      {row('raw', `${pct(t.raw)}%  ${bar(t.raw, t.threshold)}`)}
      {row('smooth', `${pct(t.ema)}%  ${bar(t.ema, t.threshold)}`)}
      {row('thresh', `${pct(t.threshold)}%   pre-connect at ${pct(t.preconnectThreshold)}%`)}
      {row('level', `${(t.levelDbfs ?? 0).toFixed(0)} dBFS   floor ${(t.noiseFloorDbfs ?? 0).toFixed(0)}   gate ${t.gateOpen ? 'OPEN' : 'shut'}`)}
      {row('infer', `${t.inferCount ?? 0} runs, ${(t.avgInferMs ?? 0).toFixed(1)} ms avg`)}
      {row(
        'sessions',
        `pre ${t.preconnect ?? 0} · confirmed ${t.confirm ?? 0} · dropped ${t.abandon ?? 0}` +
          ` · throttled ${t.throttled ?? 0}` +
          (t.lastLatencyMs != null ? ` · head start ${t.lastLatencyMs} ms` : '')
      )}
    </div>
  );
}
