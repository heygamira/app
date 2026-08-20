// Browser half of the Gemini Live voice chat.
//
// The microphone and speaker are Web Audio; the conversation is Gemini Live.
// Two things this file deliberately does not do:
//
//   1. It never holds the Gemini API key. The backend mints a one-use
//      ephemeral token with the model, modalities, system instruction and tool
//      catalogue already pinned into it, and hands it over through the normal
//      authenticated API client.
//   2. It never decides what a tool call is allowed to do. Client-only tools go
//      through an allowlisted UI dispatcher; everything else is forwarded to
//      the backend, which re-checks ownership, permission and arguments before
//      anything happens.
//
// Audio contract:
//   up   - raw PCM, 16-bit little-endian, mono, rate declared in the mime type
//   down - raw PCM, 16-bit little-endian, mono, 24 kHz
//
// @google/genai is imported dynamically: it is ~400 kB and most sessions on
// this app never open the microphone, so it should not sit in the entry chunk.

import {
  isClientTool,
  toolError,
  validateFunctionCall,
} from '@/lib/voiceTools';

// Usage reporting for the local server console. Optional and non-authoritative:
// losing an update costs nothing because the API reports cumulative totals.
export const DEFAULT_USAGE_URL =
  import.meta.env.VITE_GEMINI_USAGE_URL || '/gemini-token/usage';

const OUTPUT_RATE = 24_000;

// How far ahead of the clock to (re)start playback after a gap. Enough for the
// audio thread to render a buffer comfortably, short enough that nobody hears
// it as delay.
const PLAYBACK_LEAD = 0.12;
// Below this much scheduled runway, treat the stream as having run dry and
// rebuild the cushion rather than chasing the clock.
const MIN_SLACK = 0.02;

// Runs on the audio thread: batches mic samples and converts float -> PCM16.
// Delivered as a blob URL so it needs no separate file in the build.
//
// Only used when this module opens the microphone itself. When the wake-word
// engine is running it already owns a worklet on the same stream, and passing
// its `audioSource` here shares that one rather than starting a second graph.
export const CAPTURE_WORKLET = `
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    // ~50ms per message. Every millisecond spent batching here is a
    // millisecond added to how long Gamira takes to start replying, so this
    // is kept short; it is still coarse enough not to flood the main thread.
    this._target = Math.round(sampleRate / 20);
    this._chunks = [];
    this._length = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    this._chunks.push(new Float32Array(channel));
    this._length += channel.length;
    if (this._length < this._target) return true;

    const merged = new Float32Array(this._length);
    let offset = 0;
    for (const chunk of this._chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    this._chunks = [];
    this._length = 0;

    const pcm = new Int16Array(merged.length);
    for (let i = 0; i < merged.length; i++) {
      const s = Math.max(-1, Math.min(1, merged[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    this.port.postMessage(pcm.buffer, [pcm.buffer]);
    return true;
  }
}
registerProcessor('pcm-capture', PCMCapture);
`;

function floatToPcm16(input) {
  const pcm = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

export function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const STRIDE = 0x8000; // chunked so we never blow the argument limit
  for (let i = 0; i < bytes.length; i += STRIDE) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + STRIDE));
  }
  return btoa(binary);
}

export function base64ToInt16(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  // A trailing odd byte would throw when viewed as Int16.
  const usable = bytes.length - (bytes.length % 2);
  return new Int16Array(bytes.buffer, 0, usable / 2);
}

/**
 * Every functionCall in one Live message, wherever the SDK put it.
 *
 * The shape has moved between SDK versions, so all the known places are read
 * and de-duplicated by call id. Missing one means the model waits forever for
 * a response that never comes.
 *
 * @param {object} message
 * @returns {Array<object>}
 */
export function extractFunctionCalls(message) {
  const found = [];
  const push = (calls) => {
    if (Array.isArray(calls)) found.push(...calls);
  };

  push(message?.toolCall?.functionCalls);
  push(message?.serverContent?.toolCall?.functionCalls);
  push(message?.functionCalls);
  for (const part of message?.serverContent?.modelTurn?.parts || []) {
    if (part?.functionCall) found.push(part.functionCall);
  }

  const seen = new Set();
  return found.filter((call) => {
    const key = call?.id || `${call?.name}:${JSON.stringify(call?.args ?? {})}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Opens a live voice session. Returns immediately with a handle; connection
 * progress arrives through onStatus.
 *
 * @param {object} opts
 * @param {((opts: {provisional: boolean}) => Promise<object>) | null} [opts.createSession]
 *        asks the backend for a session + token
 * @param {((sessionId: string) => void) | null} [opts.closeSession]
 *        releases the backend's record of this session. Called exactly once,
 *        however the session ended.
 * @param {((sessionId: string, turns: Array<{role: string, text: string}>,
 *          opts: {final: boolean}) => void) | null} [opts.storeTranscript]
 *        keeps what was said. Batched every few seconds and once on the way out.
 * @param {(sessionId: string, calls: Array<object>) => Promise<object>} [opts.sendToolCalls]
 * @param {(name: string, args: object) => Promise<object>} [opts.dispatchClientTool]
 * @param {(result: {name: string, response: object}) => void} [opts.onToolResult]
 *        a backend tool finished. The app watches this so something done by
 *        voice can be reflected on the screen the person is looking at.
 * @param {(request: object) => void} [opts.onConfirmationRequired]
 * @param {(resolved: {decisionId: string, response: object}) => void} [opts.onConfirmationResolved]
 *        a confirmation was answered out loud rather than on screen
 * @param {string} [opts.usageUrl]
 * @param {(s: string) => void} [opts.onStatus]      'connecting'|'listening'|'speaking'|'working'|'closed'
 * @param {(t: string) => void} [opts.onTranscript]  model transcript text, streamed
 * @param {(t: string, meta?: {live?: boolean}) => void} [opts.onUserTranscript]
 *        what the *person* said. Called with `{live: true}` for the interim
 *        transcript that updates while they are still speaking, and again
 *        without it when the server finalises the sentence.
 * @param {() => void} [opts.onTurnEnd]              the model finished or was cut off
 * @param {(u: object) => void} [opts.onUsage]       cumulative token usage for this session
 * @param {(info: object) => void} [opts.onSession]  the backend session, once created
 * @param {(e: Error) => void} [opts.onError]
 * @param {MediaStream} [opts.stream]         an already-open microphone to borrow
 * @param {AudioContext} [opts.captureCtx]    an already-running capture context to borrow
 * @param {AudioContext} [opts.playbackCtx]   an already-running playback context to borrow
 * @param {{subscribe: (fn: (chunk: Float32Array) => void) => (() => void)}} [opts.audioSource]
 *        an existing mic tap, in place of building a second worklet
 * @param {boolean} [opts.provisional]  open this session speculatively; it does
 *        not count against the hourly quota until `promote` is called
 * @param {boolean} [opts.autoStream]   start sending audio as soon as the socket
 *        opens. False keeps the session connected but silent until
 *        `beginStreaming()` — which is how the wake word pre-connects.
 * @param {string | null} [opts.openingBrief]  a bracketed note telling Gamira
 *        why the app opened this conversation. Sent as the first turn, so she
 *        speaks before anybody has said anything to her.
 * @param {boolean} [opts.listenAfterBrief]  open the microphone once she has
 *        finished the opening brief. False means she says her piece and the
 *        session stays silent, which is what a pure announcement would be.
 * @param {() => void} [opts.onOpen]    the socket reached a usable state
 * @returns {{stop: () => void, beginStreaming: () => void,
 *   prependAudio: (pcm: Int16Array) => void, brief: (text: string) => void,
 *   resolveConfirmation: (decisionId: string, response: object) => void}}
 */
export function startVoiceSession({
  createSession = null,
  closeSession = null,
  storeTranscript = null,
  sendToolCalls = null,
  dispatchClientTool = null,
  onConfirmationRequired = () => {},
  onConfirmationResolved = () => {},
  usageUrl = DEFAULT_USAGE_URL,
  onStatus = () => {},
  onTranscript = () => {},
  onUserTranscript = () => {},
  onToolResult = () => {},
  onTurnEnd = () => {},
  onUsage = () => {},
  onSession = () => {},
  onError = () => {},
  onOpen = () => {},
  stream: borrowedStream = null,
  captureCtx: borrowedCaptureCtx = null,
  playbackCtx: borrowedPlaybackCtx = null,
  audioSource = null,
  provisional = false,
  autoStream = true,
  openingBrief = null,
  listenAfterBrief = true,
} = {}) {
  let stopped = false;
  let session = null;
  let stream = borrowedStream;
  let captureCtx = borrowedCaptureCtx;
  let playbackCtx = borrowedPlaybackCtx;
  let workletUrl = null;
  let sourceNode = null;
  let workletNode = null;
  let sinkNode = null;
  let backendSessionId = null;
  let released = false;
  let unsubscribeAudio = null;

  // What this session built and must therefore tear down. Anything borrowed
  // belongs to the wake-word engine and outlives the conversation — closing it
  // would take the microphone away from the thing that listens for the next one.
  const owned = {
    stream: !borrowedStream,
    captureCtx: !borrowedCaptureCtx,
    playbackCtx: !borrowedPlaybackCtx,
  };

  // Audio captured before the socket was ready, flushed the moment it opens.
  let pending = [];
  let streaming = autoStream;

  // Scheduled playback buffers, so an interrupt can cut them off mid-flight.
  let queued = [];
  let playHead = 0;
  // Whether the model is mid-utterance, so "speaking" is announced once per
  // turn instead of once per audio chunk.
  let speaking = false;
  // How many times playback ran dry. Surfaced on the handle so a stuttering
  // connection is measurable rather than a matter of opinion.
  let underruns = 0;
  // A goodbye in progress: she is finishing a sentence and the session closes
  // when she has. See `finish()`.
  let finishing = null;
  // When the far end last sent anything for this turn — audio or transcript.
  // `finish()` needs it: a tool call usually arrives *before* the audio of the
  // sentence it was called in, so "is she speaking right now" is false at
  // exactly the moment the goodbye has to be waited for.
  let lastContentAt = 0;
  let opened = false; // did the socket ever reach a usable state?

  // Tool-call bookkeeping.
  //
  // `handledCallIds` is the client-side guard against running the same call
  // twice if the SDK delivers a message more than once. The backend has its own
  // idempotency key for the same reason; this one just avoids the round trip.
  const handledCallIds = new Set();
  // Calls waiting on a person to confirm, keyed by decision id — so a tapped
  // answer can find the call it belongs to, and so the dialog can be closed
  // when the answer arrives some other way.
  const awaitingConfirmation = new Map();
  let toolsInFlight = 0;

  // The microphone stops feeding the model while a tool call is resolving, and
  // only then.
  //
  // It used to stop for an open confirmation too, which made a spoken answer
  // impossible: the person said "yes" into a muted microphone and the
  // conversation sat there until somebody touched the screen. That is the
  // wrong trade for a voice companion, and worst for the person least able to
  // reach the phone. What the mute was really protecting against — the model
  // hearing the room, taking another turn and proposing the same thing twice —
  // is handled where it belongs now: the backend returns the confirmation
  // already open rather than raising a second one.
  const micLive = () => !stopped && toolsInFlight === 0;

  const stopQueued = () => {
    queued.forEach((node) => {
      try { node.stop(); } catch { /* already ended */ }
    });
    queued = [];
    playHead = 0;
    speaking = false;
  };

  /**
   * Tell the backend this session is over. Once, however it ended.
   *
   * This has to live here rather than in the caller. A session can end three
   * ways — stopped by hand, closed by the far end, or failed — and only the
   * first was ever released, so the other two left a row holding one of the
   * two concurrent slots for its full half-hour lifetime. That was survivable
   * while a session could only begin with a button press. A wake word can start
   * them all day, and two leaked rows lock the microphone out completely.
   */
  const release = () => {
    if (released || !backendSessionId) return;
    released = true;
    try {
      closeSession?.(backendSessionId);
    } catch {
      // The row expires on its own; a failed release is not worth surfacing.
    }
  };

  const cleanup = () => {
    finishing?.cancel();
    finishing = null;
    // Before `stopped`, or the flush refuses to run — and this is the flush
    // that carries the end of the conversation.
    flushTranscript({ final: true });
    stopped = true;
    try { session?.close(); } catch { /* already gone */ }
    session = null;
    stopQueued();
    awaitingConfirmation.clear();
    pending = [];
    try { unsubscribeAudio?.(); } catch { /* ignore */ }
    unsubscribeAudio = null;
    try { workletNode?.disconnect(); } catch { /* ignore */ }
    try { sinkNode?.disconnect(); } catch { /* ignore */ }
    try { sourceNode?.disconnect(); } catch { /* ignore */ }
    if (owned.stream) stream?.getTracks().forEach((track) => track.stop());
    if (owned.captureCtx) { try { captureCtx?.close(); } catch { /* ignore */ } }
    if (owned.playbackCtx) { try { playbackCtx?.close(); } catch { /* ignore */ } }
    if (workletUrl) URL.revokeObjectURL(workletUrl);
    workletUrl = null;
    release();
  };

  const fail = (err) => {
    if (stopped) return;
    cleanup();
    onError(err instanceof Error ? err : new Error(String(err)));
    onStatus('closed');
  };

  const reportUsage = (model, usage) => {
    const payload = {
      sessionId: backendSessionId || 'unknown',
      model,
      totalTokenCount: usage.totalTokenCount || 0,
      promptTokenCount: usage.promptTokenCount || 0,
      responseTokenCount: usage.responseTokenCount || 0,
      promptDetails: usage.promptTokensDetails || [],
      responseDetails: usage.responseTokensDetails || [],
    };
    onUsage(payload);
    if (!usageUrl) return;
    // Fire and forget: the server console shows it, and losing one update
    // costs nothing because the next one is cumulative too.
    fetch(usageUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {});
  };

  // ~10 seconds at 50 ms a chunk. A socket that has not opened by then is not
  // going to, and the buffer must not grow without limit either way.
  const MAX_PENDING = 200;

  const sendNow = (pcm, rate) => {
    session.sendRealtimeInput({
      audio: { data: bytesToBase64(pcm.buffer), mimeType: `audio/pcm;rate=${rate}` },
    });
  };

  /**
   * Send one chunk of PCM16 upstream, hold it, or drop it.
   *
   * Three cases, and the difference between them matters:
   *
   * - **Drop** while a tool call is resolving or a confirmation dialog is on
   *   screen. The model must not hear the room, take another turn, and ask for
   *   the same thing again while the person is still reading the first one.
   *   Holding this audio would be worse than losing it: it would arrive later,
   *   out of context.
   * - **Hold** while the socket is still opening. The person has already
   *   started their sentence — "Gamira, did I take my medicine?" is one breath,
   *   and the question half lands during the handshake.
   * - **Drop** while this session is speculative and unconfirmed. Not lost: the
   *   wake-word engine's ring buffer holds it, and replays it on confirmation.
   *   Buffering here as well would send those seconds twice.
   */
  const sendAudio = (pcm, rate) => {
    if (stopped || !pcm.length) return;
    if (!micLive()) return;
    if (!streaming) return;

    if (!session || !opened) {
      pending.push(pcm);
      if (pending.length > MAX_PENDING) pending.shift();
      return;
    }
    try {
      sendNow(pcm, rate);
    } catch (err) {
      fail(err);
    }
  };

  const flushPending = (rate) => {
    if (!session || !opened || !streaming || !pending.length) return;
    const held = pending;
    pending = [];
    for (const pcm of held) {
      try {
        sendNow(pcm, rate);
      } catch (err) {
        fail(err);
        return;
      }
    }
  };

  const play = (base64) => {
    if (stopped || !playbackCtx) return;
    lastContentAt = Date.now();
    const pcm = base64ToInt16(base64);
    if (!pcm.length) return;

    const buffer = playbackCtx.createBuffer(1, pcm.length, OUTPUT_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;

    const node = playbackCtx.createBufferSource();
    node.buffer = buffer;
    node.connect(playbackCtx.destination);

    // Each chunk is butted against the previous one. The only question is what
    // to do when there is nothing left scheduled ahead of the clock, which
    // happens at the start of every turn and again whenever the network
    // stutters.
    //
    // Starting at `currentTime` is the obvious answer and the wrong one: it
    // asks the audio thread to render a buffer that is already due, so the
    // start of the reply crackles, and every subsequent hiccup snaps the
    // schedule back to "now" and crackles again. Over a bursty connection that
    // is continuous jitter rather than an occasional glitch.
    //
    // Instead, rebuild a small cushion. PLAYBACK_LEAD of latency is inaudible
    // in a conversation; the dropouts it prevents are not.
    if (playHead < playbackCtx.currentTime + MIN_SLACK) {
      playHead = playbackCtx.currentTime + PLAYBACK_LEAD;
      underruns += 1;
    }
    node.start(playHead);
    playHead += buffer.duration;

    queued.push(node);
    node.onended = () => { queued = queued.filter((n) => n !== node); };
    // Only on the transition. Gemini sends audio in small, frequent chunks, and
    // announcing "speaking" on every one of them puts a state update between
    // the scheduler and the buffer it is trying to queue.
    if (!speaking) {
      speaking = true;
      onStatus('speaking');
    }
  };

  /**
   * Send one function response back, with its original id and name.
   *
   * The id is what ties an answer to its question. Sending a response with the
   * wrong id makes the model attribute a result to something else, which is
   * worse than never answering.
   */
  const sendToolResponse = (call, response) => {
    if (stopped || !session) return;
    try {
      session.sendToolResponse({
        functionResponses: [{ id: call.id, name: call.name, response }],
      });
    } catch (err) {
      // A failed response must not tear the session down: the person is still
      // mid-conversation, and the model will simply ask again.
      // eslint-disable-next-line no-console
      console.warn('Gamira voice: could not send a tool response', err);
    }
  };

  /**
   * Tell the model something that happened outside the conversation.
   *
   * Only used for one thing: a confirmation answered by tapping the screen
   * rather than out loud. The model cannot hear a button, and its function
   * response for that call has already gone (it said a confirmation was open),
   * so there is no question left to answer — this is the outcome arriving by
   * the only other route there is.
   *
   * Bracketed, and phrased about them rather than as them, because it is not
   * something they said. It never reaches the stored transcript either: that
   * is built from what the microphone heard.
   */
  const notify = (text) => {
    if (stopped || !session) return;
    try {
      session.sendClientContent({
        turns: [{ role: 'user', parts: [{ text }] }],
        turnComplete: true,
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('Gamira voice: could not pass on a screen answer', err);
    }
  };

  const handleToolCalls = async (rawCalls) => {
    const backendCalls = [];
    const backendByKey = new Map();

    for (const raw of rawCalls) {
      const checked = validateFunctionCall(raw);
      if (!checked.ok) {
        // No id means there is nothing to answer against; the model will
        // recover on its own turn.
        if (checked.id) {
          sendToolResponse(
            { id: checked.id, name: checked.name || 'unknown' },
            toolError('invalid_arguments', 'I could not read that request.', {
              reason: checked.reason,
            })
          );
        }
        continue;
      }

      const { id, name, args } = checked;
      if (handledCallIds.has(id)) {
        sendToolResponse({ id, name }, toolError(
          'duplicate_call',
          'That was already handled — nothing was done twice.'
        ));
        continue;
      }
      handledCallIds.add(id);

      if (isClientTool(name)) {
        if (!dispatchClientTool) {
          sendToolResponse({ id, name }, toolError(
            'dependency_unavailable',
            'I cannot do that from this screen.'
          ));
          continue;
        }
        try {
          const response = await dispatchClientTool(name, args);
          sendToolResponse({ id, name }, response);
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('Gamira voice: a client tool failed', err);
          sendToolResponse({ id, name }, toolError(
            'action_failed',
            'That did not work. Nothing changed.'
          ));
        }
        continue;
      }

      backendCalls.push({ id, name, arguments: args });
      backendByKey.set(id, { id, name });
    }

    if (!backendCalls.length) return;
    if (!sendToolCalls || !backendSessionId) {
      for (const call of backendCalls) {
        sendToolResponse(call, toolError(
          'dependency_unavailable',
          'I cannot reach your records right now.'
        ));
      }
      return;
    }

    toolsInFlight += 1;
    onStatus('working');
    try {
      const body = await sendToolCalls(backendSessionId, backendCalls);
      for (const result of body?.results || []) {
        const call = backendByKey.get(result.id) || {
          id: result.id,
          name: result.name,
        };
        if (result.requires_confirmation && result.decision_id) {
          awaitingConfirmation.set(result.decision_id, call);
          onConfirmationRequired({
            decisionId: result.decision_id,
            prompt: result.confirmation_prompt,
            toolName: call.name,
          });
          // The response goes out now, not when somebody taps. It says
          // `confirmation_required` and carries the exact sentence to read and
          // the id to answer against — nothing that could be mistaken for the
          // action having happened. Withholding it left the model waiting on an
          // answer that never came, so it could not react to anything at all,
          // including the person saying yes.
          sendToolResponse(call, result.response);
          continue;
        }
        // An answer to a confirmation, spoken rather than tapped. The dialog on
        // screen is about a decision that is now settled, so it goes.
        const resolved = result.response?.resolved_decision_id;
        if (resolved && awaitingConfirmation.delete(resolved)) {
          onConfirmationResolved({ decisionId: resolved, response: result.response });
        }
        // Something happened to the record, by voice, on whatever screen they
        // are looking at. Until this existed the screen only heard about
        // changes that went through a confirmation dialog — so an alert
        // withdrawn out loud left its own "your family knows" dialog sitting
        // there, saying something that was no longer true.
        try {
          onToolResult({ name: call.name, response: result.response });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn('Gamira voice: a screen could not handle a tool result', err);
        }
        sendToolResponse(call, result.response);
      }
    } catch (err) {
      // The whole batch failed to reach the backend. Each call gets a
      // structured answer so the model can say what went wrong, and the
      // session stays open.
      for (const call of backendCalls) {
        sendToolResponse(call, toolError(
          err?.code === 'network_unavailable' ? 'dependency_unavailable' : 'action_failed',
          'I could not reach your records just now.'
        ));
      }
    } finally {
      toolsInFlight = Math.max(0, toolsInFlight - 1);
      if (micLive()) onStatus('listening');
    }
  };

  let inputRate = 16_000;

  // Transcript, batched. Both sides arrive a few words at a time, and a request
  // per fragment would put dozens of round trips alongside the audio path this
  // file spends its effort keeping clear.
  let pendingTurns = [];
  let transcriptTimer = null;

  const flushTranscript = ({ final = false } = {}) => {
    if (transcriptTimer) {
      clearTimeout(transcriptTimer);
      transcriptTimer = null;
    }
    if (!pendingTurns.length || !backendSessionId || !storeTranscript) return;
    // Consecutive fragments from the same speaker are one thing said, and are
    // joined here rather than stored as a row per syllable.
    const turns = [];
    for (const turn of pendingTurns) {
      const last = turns[turns.length - 1];
      if (last && last.role === turn.role) last.text += turn.text;
      else turns.push({ ...turn });
    }
    pendingTurns = [];
    const cleaned = turns
      .map((turn) => ({ role: turn.role, text: turn.text.trim() }))
      .filter((turn) => turn.text);
    if (!cleaned.length) return;
    try {
      storeTranscript(backendSessionId, cleaned, { final });
    } catch {
      // A lost transcript must never disturb the conversation producing it.
    }
  };

  const recordTurn = (role, text) => {
    if (stopped || !text) return;
    pendingTurns.push({ role, text });
    if (!transcriptTimer) transcriptTimer = setTimeout(flushTranscript, 4000);
  };

  const handle = {
    /**
     * End the conversation once she has finished saying goodbye.
     *
     * `stop()` is immediate and correct for a button: somebody who pressed
     * stop wants it stopped. It is wrong for the word "bye", which is the
     * other way people end a conversation — the model says "talk to you
     * later" and calls `end_conversation` in the same turn, and tearing the
     * session down on the tool call cut her off mid-word every time. The
     * audio for that sentence is *already scheduled* in the playback graph;
     * `cleanup` stops every node in it.
     *
     * So: stop listening at once — nothing said after goodbye is meant for
     * her — then wait for the turn to complete and the scheduled audio to
     * drain, and close. `TIMEOUT` is the backstop, because a session that
     * will not close is worse than one word clipped.
     */
    finish() {
      if (stopped) return;
      if (finishing) return;
      streaming = false;
      pending = [];

      const TIMEOUT = 12_000;
      // Nothing from the far end for this long, with nothing left to play,
      // means the turn is over whether or not `turnComplete` ever arrived.
      // Needed because a tool call typically arrives before the audio of the
      // sentence it belongs to: `speaking` is false at that moment, and
      // treating that as "she has finished" closes the session before she has
      // said a word — which is the bug this whole method exists for.
      const QUIET_MS = 2500;
      const startedAt = Date.now();
      let turnDone = false;
      let timer = null;

      const drained = () =>
        !queued.length &&
        (!playbackCtx || playHead <= playbackCtx.currentTime + 0.05);
      const quiet = () => Date.now() - Math.max(lastContentAt, startedAt) > QUIET_MS;

      const check = () => {
        timer = null;
        if (stopped) return;
        if (((turnDone || quiet()) && drained()) || Date.now() - startedAt > TIMEOUT) {
          finishing = null;
          handle.stop();
          return;
        }
        timer = setTimeout(check, 120);
      };

      finishing = {
        turnEnded() {
          turnDone = true;
        },
        cancel() {
          if (timer) clearTimeout(timer);
          timer = null;
        },
      };
      check();
    },

    stop() {
      if (stopped) return;
      const sessionId = backendSessionId;
      cleanup();
      onStatus('closed');
      return sessionId;
    },

    /**
     * Start sending audio on a session opened with `autoStream: false`.
     *
     * Everything buffered since the socket opened goes first, so a speculative
     * connection loses nothing: from the model's point of view the person
     * simply started talking, and it never hears the room before that.
     */
    beginStreaming() {
      if (stopped || streaming) return;
      streaming = true;
      if (!opened) return; // onopen will flush and announce
      flushPending(inputRate);
      if (micLive()) onStatus('listening');
    },

    /**
     * Put audio in front of everything captured since. Used to replay the
     * wake-word engine's ring buffer, which holds the moments before this
     * session existed at all — the wake word itself and whatever came with it.
     *
     * Call this before `beginStreaming`, which is what actually sends it.
     */
    prependAudio(pcm) {
      if (stopped || !pcm?.length) return;
      pending.unshift(pcm);
    },

    get streaming() { return streaming; },

    /** Playback health: how many times the audio stream ran dry. */
    get underruns() { return underruns; },

    /**
     * A person answered a confirmation *on the screen*. Tell the model.
     *
     * Called with whatever the backend returned from confirm or reject, so what
     * the model hears is the persisted result — never an optimistic one.
     *
     * Answering out loud does not come through here: that path is a real tool
     * call, `confirm_pending_action`, and it gets a real function response.
     */
    resolveConfirmation(decisionId, response) {
      const call = awaitingConfirmation.get(decisionId);
      if (!call) return; // already answered, most likely out loud
      awaitingConfirmation.delete(decisionId);
      notify(
        response?.status === 'ok'
          ? `[They answered on the screen: yes. ${response.message || 'It is done.'}]`
          : '[They answered on the screen: no. Nothing was changed.]'
      );
      if (micLive()) onStatus('listening');
    },

    /**
     * Say something the app has decided needs saying, in an open session.
     *
     * The same bracketed-note mechanism as the opening brief, for the case
     * where the reason arrives after the conversation started — a watch flag
     * landing mid-chat, an SOS countdown starting while she is already
     * talking. The persona knows a bracketed note is the app speaking and not
     * the person, and is told never to read one out.
     */
    brief(text) {
      if (stopped || !text) return;
      notify(text);
    },

    get sessionId() {
      return backendSessionId;
    },
  };

  (async () => {
    try {
      onStatus('connecting');

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('This browser cannot access the microphone.');
      }
      if (typeof createSession !== 'function') {
        throw new Error('Gamira voice was started without a session source.');
      }

      const created = await createSession({ provisional });
      const token = created?.token;
      const model = created?.model;
      const apiVersion = created?.api_version || created?.apiVersion;
      backendSessionId = created?.session_id || created?.sessionId || null;
      if (!token || !model) {
        throw new Error('Gamira could not start a voice session just now.');
      }
      onSession(created);
      if (stopped) {
        // Abandoned while the backend was still answering. The row exists now
        // even though nothing will ever use it — a speculative session that is
        // dropped after two seconds hits this every time the round trip is
        // slower than that.
        release();
        return;
      }

      // Borrowed where the wake-word engine already opened one. That removes
      // the permission check, the device open and two context resumes from the
      // path between saying "Gamira" and being heard.
      //
      // Skipped entirely when `audioSource` was handed over instead: that is
      // the native engine's raw-PCM tap (see nativeEngine.js), which is the
      // *only* way this app gets microphone audio on a platform where
      // `getUserMedia` itself does not work. Calling it anyway here would
      // fail before ever reaching the `audioSource` branch below.
      if (!stream && !audioSource) {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            // Without echo cancellation the mic hears the speaker and Gemini
            // interrupts itself in a loop.
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (stopped) return;
      }

      // 16 kHz is what the API wants natively, but a browser may hand back a
      // different rate. Whatever we actually get is declared in the mime type
      // and resampled server-side, so there is no resampling to do here.
      if (!captureCtx) captureCtx = new AudioContext({ sampleRate: 16_000 });
      if (!playbackCtx) playbackCtx = new AudioContext({ sampleRate: OUTPUT_RATE });
      await captureCtx.resume();
      await playbackCtx.resume();
      if (stopped) return;

      inputRate = Math.round(captureCtx.sampleRate);

      // Mic capture starts here, before the network round trip below, not
      // after it. It used to run last — attached only once `ai.live.connect`
      // had already resolved — which cost nothing on the web engine (a
      // worklet node clipped onto a stream that was already open is instant)
      // but was a real, avoidable delay on the native engine, where
      // `audioSource.subscribe` means physically closing the wake-word's
      // `AudioRecord` and reopening it in `VOICE_COMMUNICATION` mode — see
      // `WakeWordService.runRecorderSession`, measured at a few hundred ms.
      // Stacked after the token mint and WebSocket handshake, that was pure
      // added latency between the wake word and Gemini actually hearing
      // anything. Started here instead, it overlaps with that round trip for
      // free: `sendAudio` already drops or buffers whatever arrives before
      // the socket is open (see its docblock), so nothing downstream needed
      // to change to make early chunks safe.
      if (audioSource) {
        // The wake-word engine already taps this stream; a second worklet on
        // the same graph would only duplicate the work.
        unsubscribeAudio = audioSource.subscribe((chunk) => {
          sendAudio(floatToPcm16(chunk), inputRate);
        });
      } else {
        workletUrl = URL.createObjectURL(
          new Blob([CAPTURE_WORKLET], { type: 'application/javascript' })
        );
        await captureCtx.audioWorklet.addModule(workletUrl);
        if (stopped) return;

        sourceNode = captureCtx.createMediaStreamSource(stream);
        workletNode = new AudioWorkletNode(captureCtx, 'pcm-capture');
        workletNode.port.onmessage = (event) => {
          if (stopped) return;
          sendAudio(new Int16Array(event.data), inputRate);
        };
        sourceNode.connect(workletNode);

        // The worklet produces no output, but Chrome only pulls from nodes that
        // reach the destination. A muted gain node keeps the graph alive without
        // routing the microphone back to the speakers.
        sinkNode = captureCtx.createGain();
        sinkNode.gain.value = 0;
        workletNode.connect(sinkNode);
        sinkNode.connect(captureCtx.destination);
      }

      const { GoogleGenAI, Modality } = await import('@google/genai');
      if (stopped) return;

      const ai = new GoogleGenAI({
        apiKey: token,
        // The session has to open on the surface the token was minted on: the
        // 2.5 native-audio features live on v1beta, the 3.1 preview on v1alpha.
        httpOptions: { apiVersion: apiVersion || 'v1alpha' },
      });

      session = await ai.live.connect({
        model,
        // No tools, instruction or modalities here on purpose: they are pinned
        // into the ephemeral token by the backend, so the browser cannot widen
        // what this session may do.
        config: {
          responseModalities: [Modality.AUDIO],
          outputAudioTranscription: {},
          // Asked for here as well as pinned into the token. This object
          // *replaces* the token's setup config rather than merging with it,
          // so leaving it out was quietly narrowing what the backend had
          // already decided — and the person's own side of the transcript is
          // the half this app is for.
          inputAudioTranscription: {},
        },
        callbacks: {
          onopen: () => {
            opened = true;
            onOpen();
            // The opening brief is *not* sent from here. This callback runs
            // inside `await ai.live.connect(...)`, before `session` has been
            // assigned, so `notify` would hit its own `!session` guard and
            // drop it — silently, which is the worst way for a feature whose
            // whole job is to speak first to fail. It goes below instead.
            if (streaming) {
              flushPending(inputRate);
              onStatus('listening');
            }
          },
          onmessage: (message) => {
            if (message.usageMetadata) reportUsage(model, message.usageMetadata);

            const calls = extractFunctionCalls(message);
            if (calls.length) {
              // Deliberately not awaited: the callback must return so audio
              // keeps flowing while the backend answers.
              handleToolCalls(calls).catch((err) => {
                // eslint-disable-next-line no-console
                console.warn('Gamira voice: tool handling failed', err);
              });
            }

            const content = message.serverContent;
            if (!content) return;

            // Barge-in: drop anything already scheduled so the model stops
            // talking over the user immediately.
            if (content.interrupted) {
              stopQueued();
              onTurnEnd();
              if (micLive()) onStatus('listening');
              return;
            }

            for (const part of content.modelTurn?.parts || []) {
              if (part.inlineData?.data) play(part.inlineData.data);
            }
            if (content.outputTranscription?.text) {
              lastContentAt = Date.now();
              onTranscript(content.outputTranscription.text);
              recordTurn('assistant', content.outputTranscription.text);
            }
            // The person's own words. These were being recorded for the
            // backend and shown to nobody, so the screen carried half a
            // conversation — which reads, to somebody who was not sure they
            // had been heard, exactly like not being heard.
            //
            // Two fields, and the difference is the whole reason their side of
            // the screen looked broken. `inputTranscription` is the *finalised*
            // transcript and arrives at the end of what they said — by which
            // time Gamira has usually started answering, so it was being
            // overwritten within a frame. `interimInputTranscription` is the
            // live one, updated while they are still speaking, and nothing was
            // reading it.
            //
            // The interim goes to the screen only. What is stored is the
            // final: a record built from half-heard guesses would be a worse
            // record than none.
            if (content.interimInputTranscription?.text) {
              onUserTranscript(content.interimInputTranscription.text, { live: true });
            }
            if (content.inputTranscription?.text) {
              onUserTranscript(content.inputTranscription.text);
              recordTurn('user', content.inputTranscription.text);
            }
            if (content.turnComplete) {
              speaking = false;
              onTurnEnd();
              // She has finished the sentence a goodbye was waiting on. What
              // is left is the audio already scheduled, which `finish` drains.
              finishing?.turnEnded();
              // She has said her piece. Now, and only now, does the person get
              // a microphone — for as long as the caller leaves the session
              // open, which for a proactive one is a short listening window.
              if (openingBrief && !streaming && listenAfterBrief) {
                handle.beginStreaming();
              }
              if (micLive()) onStatus('listening');
            }
          },
          onerror: (event) =>
            fail(new Error(event?.message || 'Live API connection error')),
          onclose: (event) => {
            if (stopped) return;
            const reason = event?.reason ? ` (${event.reason})` : '';
            // A socket that never opened, or one dropped with a non-normal
            // code, is a failure the user needs to see — not a silent return
            // to idle with no explanation.
            if (!opened) {
              fail(new Error(`Voice session could not start${reason}. The token may be invalid or expired.`));
              return;
            }
            if (event?.code && event.code !== 1000) {
              fail(new Error(`Voice session ended unexpectedly${reason}.`));
              return;
            }
            cleanup();
            onStatus('closed');
          },
        },
      });
      if (stopped) return;

      // Gamira going first. The brief is a bracketed note the app builds from
      // what is already on the person's screen — a dose that is late, a
      // countdown that is running — so the model words it rather than
      // inventing it.
      //
      // Nothing has been said to her, so there is no turn to answer: this
      // *is* the turn. The microphone stays shut until she has finished
      // speaking (see `turnComplete` above), because a session that opened a
      // microphone before saying why would be the microphone turning itself
      // on in somebody's home.
      if (openingBrief) {
        onStatus('working');
        notify(openingBrief);
      }
    } catch (err) {
      fail(err);
    }
  })();

  return handle;
}
