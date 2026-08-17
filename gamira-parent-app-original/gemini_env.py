"""Loads .env into os.environ for the voice scripts.

Vite reads .env too, but only hands VITE_-prefixed values to the browser —
GEMINI_API_KEY is deliberately not one of those, so nothing was reading it on
the Python side. This closes that gap without adding a dependency.

Real environment variables always win, so `GEMINI_API_KEY=... python ...`
still overrides the file.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        # Tolerate `KEY = value` and quoted values.
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
