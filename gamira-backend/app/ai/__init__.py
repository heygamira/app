"""The AI layer.

Laid out so the safety-critical parts are the ones without a model in them:

- ``facts``      deterministic figures, counted from rows
- ``context``    permission-scoped retrieval, keyed on a verified membership
- ``policy``     the verdict engine, which the model never sees or influences
- ``tools``      the entire catalogue a voice session can reach
- ``validation`` strict argument checking
- ``executor``   the ordered checks, then execution through existing services
- ``prompts``    versioned instructions
- ``provider``   the model interface, a fake and Gemini
- ``live``       authenticated Live sessions and ephemeral tokens
- ``summaries``  the weekly care summary
- ``usage``      what calls cost and how they ended

The dependency arrow only ever points from the model towards the rules, never
back.
"""

from app.ai.provider import (
    AIError,
    AIInvalidResponse,
    AIProvider,
    AIRefused,
    AIUnavailable,
    FakeAIProvider,
    get_ai_provider,
    set_ai_provider,
)
from app.ai.tools import CATALOGUE, PARENT_APP_TOOLS, ToolSpec

__all__ = [
    "CATALOGUE",
    "PARENT_APP_TOOLS",
    "AIError",
    "AIInvalidResponse",
    "AIProvider",
    "AIRefused",
    "AIUnavailable",
    "FakeAIProvider",
    "ToolSpec",
    "get_ai_provider",
    "set_ai_provider",
]
