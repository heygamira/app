"""LOCAL VOICE LAB. Not the production path, and not authenticated.

The app no longer uses this. Production Live sessions come from the backend at
``POST /api/v1/ai/live-sessions``, which requires a signed-in Gamira user,
derives the family and the cared-for person from their membership rows, applies
rate and concurrency limits, pins the approved model and tool catalogue, and
audits the session. This server does none of that: it mints a token for anyone
who can reach the port.

It survives for one reason — the server console's voice lab, where a developer
switches models, voices, proactive audio and affective dialogue at runtime to
compare them, and reads back the Live API's own usage figures. That is a
hand-testing tool on localhost, and it should never be reachable from anywhere
else.

Usage:
    pip install -r requirements-voice.txt
    export GEMINI_API_KEY=...          # PowerShell: $env:GEMINI_API_KEY = '...'
    python gemini_token_server.py
"""

import datetime
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from google import genai
from google.genai import types

from gemini_env import load_env

load_env()  # picks up GEMINI_API_KEY from .env if it is not already exported

from gamira_persona import (  # noqa: E402 - must follow load_env
    DEFAULT_SETTINGS,
    describe_models,
    live_config,
    resolve,
)

PORT = int(os.environ.get("GEMINI_TOKEN_PORT", "8787"))
# Dev default matches the Vite dev server. Set GEMINI_TOKEN_ALLOW_ORIGIN to
# lock this down to a real origin before running it anywhere but localhost.
# Comma-separated: the apps are also reachable over https for phone testing.
ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "GEMINI_TOKEN_ALLOW_ORIGIN", "http://localhost:5173"
    ).split(",")
    if origin.strip()
]

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    sys.exit("Set GEMINI_API_KEY in your environment before running this.")

# What the next session will use. Changed at runtime from the server console;
# an open session keeps whatever it started with.
settings: dict = dict(DEFAULT_SETTINGS)

# Token usage the browser reported, keyed by session. The Live API reports
# cumulative totals, so the latest figure for a session replaces the previous
# one — adding them up would multiply the bill by the number of turns.
usage_by_session: dict[str, dict] = {}


# One client per API surface, kept for the life of the process. A client built
# per request is closed as soon as it goes out of scope, and the next call
# fails with "the client has been closed".
_clients: dict[str, genai.Client] = {}


def client_for(api_version: str) -> genai.Client:
    """Ephemeral tokens are minted on the surface the session will use."""
    if api_version not in _clients:
        _clients[api_version] = genai.Client(
            api_key=api_key, http_options={"api_version": api_version}
        )
    return _clients[api_version]


def mint_token() -> dict:
    model, api_version, chosen = resolve(settings)
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    token = client_for(api_version).auth_tokens.create(
        config=types.CreateAuthTokenConfig(
            uses=1,
            # 30 minutes of conversation once connected...
            expire_time=now + datetime.timedelta(minutes=30),
            # ...but the token is only good to *open* a session for 1 minute.
            new_session_expire_time=now + datetime.timedelta(minutes=1),
            # Pin the model and config so a leaked token cannot be repurposed,
            # and so the browser inherits Gamira's persona and latency tuning
            # without any of it being shipped to the client.
            live_connect_constraints=types.LiveConnectConstraints(
                model=model, config=live_config(chosen)
            ),
            http_options=types.HttpOptions(api_version=api_version),
        )
    )
    # The browser has to connect on the same surface the token was minted on.
    return {"token": token.name, "model": model, "apiVersion": api_version}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        """A client that walks away is not worth a traceback.

        Same guard as the runner's console and the watch simulator: a window
        closing mid-request resets the connection, and the stdlib prints ten
        lines about it into the log somebody is reading.
        """
        try:
            super().handle_one_request()
        except (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            TimeoutError,
        ):
            self.close_connection = True

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = origin if origin in ALLOW_ORIGINS else ALLOW_ORIGINS[0]
        self.send_header("Access-Control-Allow-Origin", allowed)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path == "/config":
            model, api_version, chosen = resolve(settings)
            self._json(
                200,
                {
                    "settings": chosen,
                    "model": model,
                    "apiVersion": api_version,
                    "models": describe_models(),
                },
            )
            return
        if path == "/usage":
            self._json(200, {"sessions": list(usage_by_session.values())})
            return
        if path != "/token":
            self._json(404, {"error": "not found"})
            return
        try:
            self._json(200, mint_token())
        except Exception as exc:  # surface the reason to the dev console
            print(f"[token] mint failed: {exc}", file=sys.stderr)
            self._json(502, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        """Change what the next session will use.

        Only reachable from this machine: the server binds to localhost, and a
        phone reaches /token through the app's own origin via the dev server's
        proxy. Nothing on the network can retune the voice — or mint a token.
        """
        path = self.path.split("?")[0]
        if path not in ("/config", "/usage"):
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        if path == "/usage":
            session_id = str(payload.get("sessionId") or "")
            if session_id:
                usage_by_session[session_id] = {
                    "sessionId": session_id,
                    "model": payload.get("model") or settings["model"],
                    "totalTokenCount": int(payload.get("totalTokenCount") or 0),
                    "promptTokenCount": int(payload.get("promptTokenCount") or 0),
                    "responseTokenCount": int(payload.get("responseTokenCount") or 0),
                    "promptDetails": payload.get("promptDetails") or [],
                    "responseDetails": payload.get("responseDetails") or [],
                    "at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                }
            self._json(200, {"ok": True})
            return

        for key in DEFAULT_SETTINGS:
            if key in payload:
                settings[key] = payload[key]
        model, api_version, chosen = resolve(settings)
        print(
            f"[token] next session: {model} · voice {chosen['voice']}"
            f"{' · proactive' if chosen['proactive_audio'] else ''}"
            f"{' · affective' if chosen['affective_dialog'] else ''}"
        )
        self._json(200, {"settings": chosen, "model": model, "apiVersion": api_version})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[token] {fmt % args}")


if __name__ == "__main__":
    print("[token] LOCAL VOICE LAB — unauthenticated, localhost only.")
    print("[token] the apps use POST /api/v1/ai/live-sessions instead.")
    print(f"[token] serving http://localhost:{PORT}/token  (model: {settings['model']})")
    print(f"[token] allowing origins: {', '.join(ALLOW_ORIGINS)}")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[token] stopped")
