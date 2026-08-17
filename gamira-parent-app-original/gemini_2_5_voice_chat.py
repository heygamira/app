"""Continuous voice chat with Gemini over the Live API (terminal client).

Rebuilt from the original draft of this file. See VOICE_CHAT.md for the list
of bugs that version had; the fixes are marked FIX: below.

Usage:
    pip install -r requirements-voice.txt
    export GEMINI_API_KEY=...          # PowerShell: $env:GEMINI_API_KEY = '...'
    python gemini_2_5_voice_chat.py

The browser build of the same conversation lives in the React app
(src/lib/useGeminiVoice.js) and gets its credentials from
gemini_token_server.py, so the API key never leaves this machine.
"""

import asyncio
import os
import sys

try:
    import pyaudio
except ImportError:
    sys.exit("PyAudio is required:  pip install pyaudio")

from google import genai
from google.genai import types

from gemini_env import load_env

load_env()  # picks up GEMINI_API_KEY from .env if it is not already exported

from gamira_persona import MODEL, live_config  # noqa: E402 - must follow load_env

# --- Audio settings ---------------------------------------------------------
FORMAT = pyaudio.paInt16
CHANNELS = 1
INPUT_RATE = 16_000   # the Live API expects 16 kHz PCM in
OUTPUT_RATE = 24_000  # ...and returns 24 kHz PCM out
CHUNK_FRAMES = 512    # 32 ms per read; small enough to keep latency low


def drain(queue: asyncio.Queue) -> None:
    """Throw away anything still queued for playback."""
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break


async def mic_to_gemini(session, stream, loop) -> None:
    """Read the microphone and stream it up as raw PCM."""
    print("\n[mic] listening — speak, Ctrl+C to quit")
    while True:
        # read() is blocking, so it stays on a worker thread.
        # exception_on_overflow=False: a dropped buffer beats a crash.
        data = await loop.run_in_executor(None, stream.read, CHUNK_FRAMES, False)
        await session.send_realtime_input(
            audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={INPUT_RATE}")
        )


async def gemini_to_queue(session, playback: asyncio.Queue) -> None:
    """Pull model responses and hand the audio to the playback task."""
    # FIX: session.receive() deliberately ends its iteration at every
    # turn_complete. The original code awaited it once, so playback died after
    # Gemini's first reply. The outer loop re-enters it for each new turn.
    while True:
        async for message in session.receive():
            content = message.server_content
            if content is None:
                continue

            # FIX: honour barge-in. Without this, audio the model already sent
            # keeps playing over the user after they interrupt it.
            if content.interrupted:
                drain(playback)
                print("\n[interrupted]")

            if content.model_turn and content.model_turn.parts:
                for part in content.model_turn.parts:
                    # FIX: read the audio from exactly one place. The original
                    # also wrote message.data, which is a property that
                    # re-concatenates these same inline_data parts — so every
                    # chunk was played twice.
                    if part.inline_data and part.inline_data.data:
                        playback.put_nowait(part.inline_data.data)

            # FIX: with response_modalities=["AUDIO"] the model returns no text
            # parts at all, so the old `part.text` print was dead code.
            # Transcripts have to be requested explicitly (see config below).
            if content.output_transcription and content.output_transcription.text:
                print(content.output_transcription.text, end="", flush=True)
            if content.input_transcription and content.input_transcription.text:
                print(f"\n[you] {content.input_transcription.text}", flush=True)


async def queue_to_speaker(stream, playback: asyncio.Queue, loop) -> None:
    """Play queued audio without blocking the event loop."""
    while True:
        chunk = await playback.get()
        # FIX: stream.write() blocks until the buffer drains. Calling it
        # straight from the receive loop stalled the whole event loop, which
        # starved the microphone task and caused input overruns.
        await loop.run_in_executor(None, stream.write, chunk)


async def main() -> None:
    # FIX: no hard-coded fallback key. The original shipped a real API key as
    # the default value, which meant the secret was committed to the repo and
    # the `if not api_key` guard below could never fire.
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Set GEMINI_API_KEY in your environment before running this.")

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    # Shared with the browser client; the terminal one also shows what it heard.
    config = live_config(
        input_audio_transcription=types.AudioTranscriptionConfig()
    )

    audio = pyaudio.PyAudio()
    input_stream = output_stream = None
    tasks: list[asyncio.Task] = []
    loop = asyncio.get_running_loop()

    try:
        input_stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=INPUT_RATE,
            input=True,
            frames_per_buffer=CHUNK_FRAMES,
        )
        output_stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=OUTPUT_RATE,
            output=True,
            frames_per_buffer=CHUNK_FRAMES,
        )

        print(f"--- connecting to {MODEL} ---")
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            print("connected.")
            playback: asyncio.Queue = asyncio.Queue()
            tasks = [
                asyncio.create_task(mic_to_gemini(session, input_stream, loop)),
                asyncio.create_task(gemini_to_queue(session, playback)),
                asyncio.create_task(queue_to_speaker(output_stream, playback, loop)),
            ]
            # If any one task dies, stop instead of hanging on the others.
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                task.result()  # re-raise whatever went wrong
    finally:
        # FIX: cancel *and await* the tasks before closing the streams. The
        # original cancelled and immediately closed, so a task still inside
        # write() could touch a closed stream on the way out.
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        print("\nclosing streams...")
        for stream in (input_stream, output_stream):
            if stream is not None:
                stream.stop_stream()
                stream.close()
        audio.terminate()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
