"""The watch's only connection: a mailbox local to this senior's Parent App.

Why this exists: today the watch simulator is its own independent client of
the Gamira API, authenticating with the senior's own account credentials and
hitting the server directly, completely regardless of whether their Parent App
is even open. That is two always-connected clients per senior instead of one —
harmless at one family, real load at many.

It also does not match how a real watch gets data onto a phone. Whether a
watch talks Health Connect (Android), HealthKit (iOS), a vendor's own cloud
(cellular elder-care watches), or raw Bluetooth GATT (cheap fitness bands),
the one thing true in every case is that *the phone app* is the sole bridge to
a third party's backend — the watch itself never holds a credential for it.

This process is that bridge, in miniature, for the simulator:

    watch (this pairing code only, no account) <--> this relay <--> Parent App (has the account) --> Gamira API

The watch knows a pairing code (what `run.py --pair` already passes, e.g.
`sharma-senior`) and nothing else — no bearer token, no senior id, no call to
the Gamira API at all. The Parent App, already signed in, registers itself
against that same code on load. The relay's whole job is holding that mapping
and a small mailbox; the Parent App is the only thing that ever drains it and
forwards to the real backend, using its own session.

No auth here: this binds to 127.0.0.1 only, exactly like gemini_token_server.py
next to it, and holds nothing more sensitive than a heart rate reading that
has not been written yet.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("GAMIRA_WATCH_RELAY_PORT", "8021"))

_lock = threading.Lock()
# pairing_code -> the name the Parent App gave itself when it registered, so
# the watch face can say who it is paired to without ever learning a senior id.
_registered: dict[str, str] = {}
# pairing_code -> buffered readings, drained (and cleared) by the one Parent
# App instance that registered under that code.
_readings: dict[str, list[dict]] = {}
# pairing_code -> buffered device flags / SOS, drained the same way. Kept
# separate from readings so a slow reading flush never delays something
# safety-relevant sitting right behind it in the same mailbox.
_urgent: dict[str, list[dict]] = {}


def _bucket(store: dict[str, list[dict]], code: str) -> list[dict]:
    return store.setdefault(code, [])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        """A closed watch or a reloaded Parent App tab is not an error worth
        a traceback — same guard as every other local process in this repo."""
        try:
            super().handle_one_request()
        except (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            TimeoutError,
        ):
            self.close_connection = True

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return None

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path, _, query = self.path.partition("?")
        params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)

        if path == "/pair-status":
            code = params.get("code", "")
            with _lock:
                person = _registered.get(code)
            self._json(200, {"paired": person is not None, "person": person})
            return

        if path == "/outbox":
            code = params.get("pairing_code", "")
            with _lock:
                readings = _readings.pop(code, [])
                urgent = _urgent.pop(code, [])
            self._json(200, {"readings": readings, "urgent": urgent})
            return

        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        payload = self._read_json()
        if payload is None:
            self._json(400, {"error": "invalid json"})
            return

        code = str(payload.get("pairing_code") or "")
        if not code:
            self._json(400, {"error": "pairing_code required"})
            return

        if path == "/register":
            with _lock:
                _registered[code] = str(payload.get("person") or code)
            self._json(200, {"ok": True})
            return

        if path == "/ingest/readings":
            with _lock:
                _bucket(_readings, code).append(payload.get("reading") or {})
            self._json(202, {"ok": True})
            return

        if path == "/ingest/device-flags":
            with _lock:
                _bucket(_urgent, code).append({"kind": "device_flag", **payload})
            self._json(202, {"ok": True})
            return

        if path == "/ingest/sos":
            with _lock:
                _bucket(_urgent, code).append({"kind": "sos", **payload})
            self._json(202, {"ok": True})
            return

        self._json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[watch-relay] {fmt % args}")


def main() -> int:
    print(f"[watch-relay] serving http://127.0.0.1:{PORT} — loopback only")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[watch-relay] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
