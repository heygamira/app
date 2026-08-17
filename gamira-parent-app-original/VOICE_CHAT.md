# Gemini voice chat

Two clients for the same Gemini Live API conversation:

| | What it is | Entry point |
|---|---|---|
| Terminal | PyAudio mic/speaker loop | `gemini_2_5_voice_chat.py` |
| App | The Gamira mic button on the Home screen | `src/lib/geminiVoice.js` |

The app half never sees `GEMINI_API_KEY`. `gemini_token_server.py` holds the
key and mints a short-lived, model-pinned token that the browser uses instead.

## Running it

```bash
pip install -r requirements-voice.txt
export GEMINI_API_KEY=...          # PowerShell:  $env:GEMINI_API_KEY = '...'
```

**Terminal client**

```bash
python gemini_2_5_voice_chat.py
```

**In the app** — one command starts both:

```bash
python run.py        # or double-click run.cmd on Windows
```

It checks `GEMINI_API_KEY` is set, installs `node_modules` if missing, refuses
to start if either port is taken, then runs the token server on :8787 and the
dev server on :5173 with their output prefixed `[voice]` and `[app]`. Ctrl+C
stops both, and if either one dies the other is shut down with it — no
half-running stack, no stale server holding a port.

To run them separately instead:

```bash
python gemini_token_server.py      # terminal 1, serves :8787
npm run dev                        # terminal 2, serves :5173
```

Open the app and tap the microphone, or say "Gamira" to trigger the wake word.
If the token server is on another host or port, set `VITE_GEMINI_TOKEN_URL` in
`.env.local`.

Environment variables, all optional:

| Variable | Default |
|---|---|
| `GEMINI_LIVE_MODEL` | `gemini-3.1-flash-live-preview` |
| `GEMINI_TOKEN_PORT` | `8787` |
| `GEMINI_TOKEN_ALLOW_ORIGIN` | `http://localhost:5173` |
| `VITE_GEMINI_TOKEN_URL` | `http://localhost:8787/token` |

`GEMINI_API_KEY` is read from `.env` at the repo root (see `gemini_env.py`) or
from the real environment, which wins. Never give it a `VITE_` prefix — Vite
would compile it into the browser bundle.

## Latency

Gamira's voice, model and tuning all live in one place, `gamira_persona.py`.
Both clients build their config from it, so they cannot drift.

Measured first-audio latency, identical prompt and config, three runs each:

| Model | `thinking_level` | Median |
|---|---|---|
| `gemini-2.5-flash-native-audio-preview-12-2025` | unset | 2.38s |
| `gemini-2.5-flash-native-audio-preview-12-2025` | `MINIMAL` | 1.06s |
| `gemini-3.1-flash-live-preview` | `MINIMAL` | **0.59s** |

Three things were costing time, in order of size:

1. **The model.** 3.1-flash-live is roughly 4x faster to first audio than the
   2.5 native-audio preview was without thinking configured.
2. **Thinking.** Left unset, the model deliberates before answering — about a
   second per reply. `thinking_level: MINIMAL` removes it.
3. **End-of-speech detection.** Before the model is even asked, the API waits
   to be sure the person has stopped talking. `END_SENSITIVITY_HIGH` with
   `silence_duration_ms: 500` shortens that wait. `START_SENSITIVITY_HIGH`
   with `prefix_padding_ms: 200` is the counterweight — older speakers often
   start softly, and clipping the first word is worse than waiting.

Plus a smaller one on the browser side: the capture worklet batched 100 ms of
audio before sending, which is 100 ms added to every reply. Now 50 ms.

End to end, streaming a spoken question as real-time PCM, Gamira starts
answering **0.16s** after the speech ends (median of three).

A real microphone keeps streaming silence after you stop talking, and the VAD
needs those silent frames to notice the pause — a test harness that simply
stops sending audio will hang forever waiting for a reply.

## Bugs fixed from the original script

Verified against `google-genai` 1.68.0 and the Live API docs.

1. **Hard-coded API key.** The key was the default value of
   `os.environ.get("GEMINI_API_KEY", ...)`, so it sat in the source and the
   `if not api_key` guard below it could never fire. **That key is burned —
   rotate it.**
2. **Every audio chunk played twice.** The loop wrote
   `part.inline_data.data` and then also wrote `response.data`.
   `LiveServerMessage.data` is a property that re-concatenates those same
   `inline_data` parts, so all audio was written to the speaker twice.
3. **Conversation died after one reply.** `session.receive()` breaks its own
   iteration at every `turn_complete`, so a single `async for` covers exactly
   one model turn. The mic kept streaming but nothing ever played again. The
   receive loop now sits inside an outer `while True`.
4. **Blocking writes on the event loop.** `stream.write()` is synchronous;
   calling it from the async receive loop stalled the loop and starved the
   microphone task. Playback now goes through a queue and a worker thread.
5. **No barge-in.** `server_content.interrupted` was ignored, so audio already
   buffered kept playing over a user who interrupted. The queue is now flushed
   on interrupt.
6. **Dead transcript printing.** With `response_modalities: ["AUDIO"]` the
   model returns no text parts, so `part.text` never fired. Transcripts need
   `input_audio_transcription` / `output_audio_transcription` in the config.
7. **Unclean shutdown.** Tasks were cancelled but never awaited before the
   streams were closed, so a task still inside `write()` could touch a closed
   stream. `asyncio.gather` also had no failure handling, leaving one task
   hanging if the other died.
8. **Microphone feedback.** Nothing suppressed the speaker bleeding into the
   mic, so the model interrupted itself. The browser client enables echo
   cancellation; on the desktop this is left to the OS, so use headphones.

Not a bug: `gemini-2.5-flash-native-audio-preview-12-2025` is a real, current
model ID, and passing `audio=` a plain dict works — the SDK coerces it to
`types.Blob`. The rewrite passes `types.Blob` explicitly anyway.

## How the browser client works

```
mic ─► AudioWorklet ─► PCM16 ─► base64 ─► sendRealtimeInput
                                              │
speaker ◄─ AudioBufferSource queue ◄─ PCM16 ◄─┘ inlineData (24 kHz)
```

- **Capture** runs in an `AudioWorklet` (built from a blob URL, so there is no
  extra file to serve). It batches ~100 ms of float samples, converts to
  16-bit PCM, and transfers the buffer to the main thread. The worklet fills
  in 128-sample render quanta, so frames land slightly over 100 ms — that is
  expected and the API accepts variable chunk sizes.
- The capture `AudioContext` asks for 16 kHz but whatever rate the browser
  actually grants is declared in the mime type (`audio/pcm;rate=N`) and
  resampled server-side, so there is no resampling in the client.
- **Playback** schedules each 24 kHz chunk butted against the end of the
  previous one, falling back to `currentTime` if it has fallen behind. On
  `interrupted`, every scheduled node is stopped and the play head resets.
- The worklet is connected to the destination through a **zero-gain node**.
  Chrome only pulls from nodes that reach the destination, but routing the raw
  mic to the speakers would howl.

## Known limits

- The token server is a dev tool: it binds `127.0.0.1`, has no rate limiting,
  and mints a token to anyone who asks. Put it behind real auth before it goes
  anywhere near production.
- Only the English strings were added for the new voice states. The other
  eight languages fall back to English (`i18n.jsx` does this automatically)
  until translated.
- Video is not wired up. The Live API takes camera and screen frames, and the
  cookbook sample shows how, but streaming an older person's camera by default
  is a product decision, not a technical one.

## Verified

- PCM16 ⇄ base64 round-trip, including the odd-trailing-byte guard.
- Capture worklet loads and emits 3328-byte PCM frames from a live
  `getUserMedia` stream at 16 kHz.
- Playback scheduler queues three 100 ms buffers contiguously (0.300 s span)
  and stops them all on interrupt without throwing.
- Home screen with the voice server down: shows
  "Can't reach the voice server at … Start it with: python
  gemini_token_server.py", and the rest of the app stays interactive.
- Home screen with a deliberately invalid token: the handshake reaches Google
  and the rejection surfaces as "Voice session ended unexpectedly (API key not
  valid…)" rather than silently returning to idle.
- Real conversation, real key. Fed a synthesised "Hello. Who are you, and what
  can you help me with?" as live PCM. Gamira: *"Hello, I'm Gamira, here to keep
  you company and help with little things in your day. I can remind you about
  medications, chat about the news, or even pass on a message from your
  family."* Short, spoken-shaped, no markdown, right subject matter — the
  system instruction is reaching the session, including through the browser's
  ephemeral token, where it is pinned server-side and never shipped to the
  client.
- Barge-in confirmed incidentally: a looping test WAV talks over Gamira
  constantly, and each interruption cuts her off and restarts the turn.
