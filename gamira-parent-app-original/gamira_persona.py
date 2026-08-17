"""Gamira's voice, in one place.

Both clients — the terminal one (gemini_2_5_voice_chat.py) and the browser one,
via the token server — build their Live API config from here, so the two cannot
drift apart.
"""

import os

from google.genai import types

# gemini-3.1-flash-live-preview is measurably faster to first audio than the
# 2.5 native-audio preview: median 0.59s vs 1.06s over three runs each, on an
# identical prompt and config. Override with GEMINI_LIVE_MODEL if needed.
MODEL = os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")

# What each Live model will actually accept. Sending a field a model does not
# support fails the whole session, so the server console offers a toggle only
# where the model below says it exists.
#
# Checked against ai.google.dev/gemini-api/docs/live-api/capabilities on
# 17 Aug 2026. Proactive audio and affective dialogue are 2.5 native-audio
# features; the 3.1 preview has neither.
#
# The docs say those two need v1beta. They do not, at least not through an
# ephemeral token: v1beta rejects `proactivity` both when minting the token and
# when opening the session ("Unknown name \"proactivity\" at 'setup'"), while
# v1alpha accepts it in the token constraints and connects. Both surfaces were
# tried directly before settling on this; if a future SDK moves them, the
# failure is loud and lands in the console.
MODELS: dict[str, dict] = {
    "gemini-3.1-flash-live-preview": {
        "label": "3.1 Flash Live",
        "note": "Fastest to first word. No proactive audio or affective dialogue.",
        "api_version": "v1alpha",
        "proactive_audio": False,
        "affective_dialog": False,
        "thinking_level": True,
        # The half-cascade voice set. The native-audio voices below are not
        # available here.
        "voices": [
            "Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck", "Zephyr",
        ],
        "default_voice": "Aoede",
    },
    "gemini-2.5-flash-native-audio-preview-12-2025": {
        "label": "2.5 Native Audio",
        "note": "Slower to start, but can stay quiet and can match the speaker's tone.",
        "api_version": "v1alpha",
        "proactive_audio": True,
        "affective_dialog": True,
        "thinking_level": False,
        "voices": [
            "Achernar", "Achird", "Algenib", "Algieba", "Alnilam", "Aoede",
            "Autonoe", "Callirrhoe", "Charon", "Despina", "Enceladus", "Erinome",
            "Fenrir", "Gacrux", "Iapetus", "Kore", "Laomedeia", "Leda", "Orus",
            "Puck", "Pulcherrima", "Rasalgethi", "Sadachbia", "Sadaltager",
            "Schedar", "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr",
            "Zubenelgenubi",
        ],
        "default_voice": "Erinome",
    },
}

DEFAULT_SETTINGS: dict = {
    "model": MODEL,
    "voice": None,  # None means the model's own default
    "proactive_audio": False,
    "affective_dialog": False,
    "thinking_level": "MINIMAL",
}


def describe_models() -> list[dict]:
    """The registry, in the shape the server console renders."""
    return [{"id": model_id, **spec} for model_id, spec in MODELS.items()]


def resolve(settings: dict | None = None) -> tuple[str, str, dict]:
    """Clamp a set of console choices to what the chosen model supports.

    Returns ``(model_id, api_version, settings)``. A toggle the model cannot
    honour is turned off here rather than sent and rejected mid-session, and a
    voice that belongs to the other model is replaced by this one's default.
    """
    chosen = {**DEFAULT_SETTINGS, **(settings or {})}
    model_id = chosen["model"] if chosen["model"] in MODELS else MODEL
    spec = MODELS[model_id]

    chosen["model"] = model_id
    chosen["proactive_audio"] = bool(chosen["proactive_audio"]) and spec["proactive_audio"]
    chosen["affective_dialog"] = (
        bool(chosen["affective_dialog"]) and spec["affective_dialog"]
    )
    if chosen["voice"] not in spec["voices"]:
        chosen["voice"] = spec["default_voice"]
    return model_id, spec["api_version"], chosen

SYSTEM_INSTRUCTION = """\
You are Gamira, a warm and patient voice companion for an older adult living \
independently at home. Gamira is "she". Her promise is: care that talks, so \
families worry less.

HOW YOU SOUND
You are being heard, not read. Never use markdown, bullet points, headings, \
emoji or symbols — none of it can be spoken. Keep answers to one or two short \
sentences unless you are asked for more, and put the useful part first. Speak \
calmly and unhurried; warm, but not bubbly. Say numbers the way a person says \
them out loud: "one twenty over eighty", "half past four". Ask one question at \
a time, then stop and let them answer.

RESPECT
They are an adult in charge of their own life. Offer, never nag. Never scold. \
Do not call them sweetie, dear, or love, do not praise them for ordinary \
things, and never hint that they are frail, forgetful or a burden. If a dose \
was missed, mention it once, kindly, and move on. You are not there to report \
on them; if something genuinely needs a family member, say so to them first, \
openly.

LANGUAGE
Answer in whatever language they speak to you, and switch the moment they do. \
You are fluent in English, Hindi, Tamil, Telugu, Marathi, Bengali, Spanish, \
French and Chinese. If they mix languages, mix them back naturally. Never \
correct how they speak.

WHAT YOU HELP WITH
Reminders for medication, meals, water and the shape of the day. Health \
readings the app follows — heart rate, blood pressure, sleep, oxygen, activity \
— explained in plain words, not numbers alone. Family: who called, passing on \
a message, helping them reach someone. And company: a conversation, a memory, \
the news, a story, whatever they are in the mood for.

IF SOMETHING IS WRONG
If they mention chest pain, trouble breathing, a fall they cannot get up from, \
sudden weakness, confusion, slurred speech, or bleeding that will not stop: \
stay calm, tell them plainly to press the red SOS button now or call their \
emergency number, and keep talking with them until help is coming.

You are not a doctor. Never diagnose and never suggest changing a dose. \
Anything medical beyond what a reading plainly means goes to their doctor.

HONESTY
If you did not hear them, say so and ask them to say it again — never guess at \
what they meant. Only say you have done something if you actually did it. If \
you cannot do a thing, say so plainly and offer what you can do instead.
"""


def live_config(settings: dict | None = None, **overrides) -> types.LiveConnectConfig:
    """The shared Live API config. Tuned for how fast Gamira starts replying.

    ``settings`` are the console's choices; anything the chosen model does not
    support has already been dropped by ``resolve``.
    """
    model_id, _, chosen = resolve(settings)
    spec = MODELS[model_id]

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_INSTRUCTION)]
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=chosen["voice"]
                )
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                # How long a pause has to be before Gamira decides the person
                # has finished. This is the other half of the delay: it is
                # spent waiting, before the model is even asked.
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                silence_duration_ms=500,
                # Older speakers often start softly, so lean towards hearing
                # the start of speech rather than clipping it.
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                prefix_padding_ms=200,
            )
        ),
        # Keeps a long chat alive instead of hitting the context limit and
        # dropping the session mid-conversation.
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=104857,
            sliding_window=types.SlidingWindow(target_tokens=52428),
        ),
    )

    # Only what this model actually accepts, in the shape it accepts it.
    if spec["thinking_level"]:
        # Without this the model deliberates before answering, which cost
        # roughly a second per reply in testing.
        config.thinking_config = types.ThinkingConfig(
            thinking_level=chosen["thinking_level"]
        )
    if chosen["proactive_audio"]:
        # Lets Gamira stay quiet when what she heard was not addressed to her —
        # a room with a television in it, rather than a question.
        config.proactivity = types.ProactivityConfig(proactive_audio=True)
    if chosen["affective_dialog"]:
        # Her delivery follows the speaker's tone instead of one fixed reading.
        config.enable_affective_dialog = True

    for key, value in overrides.items():
        setattr(config, key, value)
    return config
