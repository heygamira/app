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

// Runs on the audio thread: batches mic samples and converts float -> PCM16.
// Delivered as a blob URL so it needs no separate file in the build.
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
 * @param {(() => Promise<object>) | null} [opts.createSession]  asks the backend for a session + token
 * @param {(sessionId: string, calls: Array<object>) => Promise<object>} [opts.sendToolCalls]
 * @param {(name: string, args: object) => Promise<object>} [opts.dispatchClientTool]
 * @param {(request: object) => void} [opts.onConfirmationRequired]
 * @param {string} [opts.usageUrl]
 * @param {(s: string) => void} [opts.onStatus]      'connecting'|'listening'|'speaking'|'working'|'closed'
 * @param {(t: string) => void} [opts.onTranscript]  model transcript text, streamed
 * @param {() => void} [opts.onTurnEnd]              the model finished or was cut off
 * @param {(u: object) => void} [opts.onUsage]       cumulative token usage for this session
 * @param {(info: object) => void} [opts.onSession]  the backend session, once created
 * @param {(e: Error) => void} [opts.onError]
 * @returns {{stop: () => void, resolveConfirmation: (decisionId: string, response: object) => void}}
 */
export function startVoiceSession({
  createSession = null,
  sendToolCalls = null,
  dispatchClientTool = null,
  onConfirmationRequired = () => {},
  usageUrl = DEFAULT_USAGE_URL,
  onStatus = () => {},
  onTranscript = () => {},
  onTurnEnd = () => {},
  onUsage = () => {},
  onSession = () => {},
  onError = () => {},
} = {}) {
  let stopped = false;
  let session = null;
  let stream = null;
  let captureCtx = null;
  let playbackCtx = null;
  let workletUrl = null;
  let sourceNode = null;
  let workletNode = null;
  let sinkNode = null;
  let backendSessionId = null;

  // Scheduled playback buffers, so an interrupt can cut them off mid-flight.
  let queued = [];
  let playHead = 0;
  let opened = false; // did the socket ever reach a usable state?

  // Tool-call bookkeeping.
  //
  // `handledCallIds` is the client-side guard against running the same call
  // twice if the SDK delivers a message more than once. The backend has its own
  // idempotency key for the same reason; this one just avoids the round trip.
  const handledCallIds = new Set();
  // Calls waiting on a person to confirm, keyed by decision id. The mic stays
  // muted while any of these are open: the model must not talk itself into a
  // second attempt while a dialog is on screen.
  const awaitingConfirmation = new Map();
  let toolsInFlight = 0;

  const micLive = () =>
    !stopped && toolsInFlight === 0 && awaitingConfirmation.size === 0;

  const stopQueued = () => {
    queued.forEach((node) => {
      try { node.stop(); } catch { /* already ended */ }
    });
    queued = [];
    playHead = 0;
  };

  const cleanup = () => {
    stopped = true;
    try { session?.close(); } catch { /* already gone */ }
    session = null;
    stopQueued();
    awaitingConfirmation.clear();
    try { workletNode?.disconnect(); } catch { /* ignore */ }
    try { sinkNode?.disconnect(); } catch { /* ignore */ }
    try { sourceNode?.disconnect(); } catch { /* ignore */ }
    stream?.getTracks().forEach((track) => track.stop());
    try { captureCtx?.close(); } catch { /* ignore */ }
    try { playbackCtx?.close(); } catch { /* ignore */ }
    if (workletUrl) URL.revokeObjectURL(workletUrl);
    workletUrl = null;
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

  const play = (base64) => {
    if (stopped || !playbackCtx) return;
    const pcm = base64ToInt16(base64);
    if (!pcm.length) return;

    const buffer = playbackCtx.createBuffer(1, pcm.length, OUTPUT_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;

    const node = playbackCtx.createBufferSource();
    node.buffer = buffer;
    node.connect(playbackCtx.destination);

    // Butt each chunk against the previous one; if we have fallen behind,
    // restart from now rather than scheduling in the past.
    const startAt = Math.max(playbackCtx.currentTime, playHead);
    node.start(startAt);
    playHead = startAt + buffer.duration;

    queued.push(node);
    node.onended = () => { queued = queued.filter((n) => n !== node); };
    onStatus('speaking');
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
          // Held back: the response goes to the model only once a person has
          // answered, so it can never say something happened before it did.
          awaitingConfirmation.set(result.decision_id, call);
          onConfirmationRequired({
            decisionId: result.decision_id,
            prompt: result.confirmation_prompt,
            toolName: call.name,
          });
          continue;
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

  const handle = {
    stop() {
      if (stopped) return;
      const sessionId = backendSessionId;
      cleanup();
      onStatus('closed');
      return sessionId;
    },

    /**
     * A person answered a confirmation. Send the outcome to the model.
     *
     * Called with whatever the backend returned from confirm or reject, so the
     * model is told the *persisted* result — never an optimistic one.
     */
    resolveConfirmation(decisionId, response) {
      const call = awaitingConfirmation.get(decisionId);
      if (!call) return;
      awaitingConfirmation.delete(decisionId);
      sendToolResponse(call, response);
      if (micLive()) onStatus('listening');
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

      const created = await createSession();
      const token = created?.token;
      const model = created?.model;
      const apiVersion = created?.api_version || created?.apiVersion;
      backendSessionId = created?.session_id || created?.sessionId || null;
      if (!token || !model) {
        throw new Error('Gamira could not start a voice session just now.');
      }
      onSession(created);
      if (stopped) return;

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

      // 16 kHz is what the API wants natively, but a browser may hand back a
      // different rate. Whatever we actually get is declared in the mime type
      // and resampled server-side, so there is no resampling to do here.
      captureCtx = new AudioContext({ sampleRate: 16_000 });
      playbackCtx = new AudioContext({ sampleRate: OUTPUT_RATE });
      await captureCtx.resume();
      await playbackCtx.resume();
      if (stopped) return;

      const inputRate = Math.round(captureCtx.sampleRate);
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
        },
        callbacks: {
          onopen: () => { opened = true; onStatus('listening'); },
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
              onTranscript(content.outputTranscription.text);
            }
            if (content.turnComplete) {
              onTurnEnd();
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

      // Mic -> worklet -> Live API
      workletUrl = URL.createObjectURL(
        new Blob([CAPTURE_WORKLET], { type: 'application/javascript' })
      );
      await captureCtx.audioWorklet.addModule(workletUrl);
      if (stopped) return;

      sourceNode = captureCtx.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(captureCtx, 'pcm-capture');
      workletNode.port.onmessage = (event) => {
        if (stopped || !session) return;
        // While a tool call is being resolved — and especially while a
        // confirmation dialog is on screen — the microphone stops feeding the
        // model. Otherwise it hears the room, takes another turn, and asks for
        // the same thing again while the person is still reading the first one.
        if (!micLive()) return;
        try {
          session.sendRealtimeInput({
            audio: {
              data: bytesToBase64(event.data),
              mimeType: `audio/pcm;rate=${inputRate}`,
            },
          });
        } catch (err) {
          fail(err);
        }
      };
      sourceNode.connect(workletNode);

      // The worklet produces no output, but Chrome only pulls from nodes that
      // reach the destination. A muted gain node keeps the graph alive without
      // routing the microphone back to the speakers.
      sinkNode = captureCtx.createGain();
      sinkNode.gain.value = 0;
      workletNode.connect(sinkNode);
      sinkNode.connect(captureCtx.destination);
    } catch (err) {
      fail(err);
    }
  })();

  return handle;
}
