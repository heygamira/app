"""A simulated Gamira watch.

Why this exists: Gamira has no wearable yet, but the Parent App, the Family
Dashboard and the API all need something producing readings before any of that
can be tested. This stands in for one — including the readings nobody wants to
wait for, like a heart rate of 140 or an oxygen saturation of 87.

How it is wired:

    watch (this process) --pairing code only--> watch relay --> Parent App --> Gamira API
                                                                          --> Family Dashboard

The watch holds no account of its own — no bearer token, no senior id, no call
to the Gamira API at all, only a pairing code (what `--pair` passes below).
That matches how a real watch actually gets data onto a phone: whether it is
Health Connect, HealthKit, a watch vendor's own cloud, or raw Bluetooth GATT,
the phone app is always the one thing with a server credential, never the
watch. The relay (`watch_relay_server.py`, in the Parent App's own folder) is
that bridge in miniature: the Parent App registers itself under this watch's
pairing code once it is signed in, and is the only thing that ever drains the
relay's mailbox and forwards to the real backend.

The simulation loop lives here rather than in the page so it keeps running
when the window is minimised, and so every send is visible in the terminal.

    python sim_server.py --relay http://127.0.0.1:8021 --port 8020 \
        --pair sharma-senior="Dad's watch"

Nothing here is clinical. The bands below decide what the *simulator* prints
as unusual so a test is easy to read; they are never sent to the apps, and
Gamira still never labels a reading healthy or unhealthy.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# A cp1252 console cannot encode the symbols used in the log lines, and an
# unhandled UnicodeEncodeError would take the simulation thread down with it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# metric -> (unit, decimal places, how many ticks between sends)
METRICS: dict[str, tuple[str, int, int]] = {
    "heart_rate": ("bpm", 0, 1),
    "oxygen_saturation": ("%", 0, 1),
    "blood_pressure_systolic": ("mmHg", 0, 3),
    "blood_pressure_diastolic": ("mmHg", 0, 3),
    "body_temperature": ("C", 1, 2),
    "steps": ("steps", 0, 5),
}

# The limits configured *on this device*. Outside them the watch face and the
# terminal say "unusual", and the family is told — as the watch's own finding,
# never as a judgement by Gamira, which does not make one.
BANDS: dict[str, tuple[float, float]] = {
    "heart_rate": (50, 110),
    "oxygen_saturation": (94, 100),
    "blood_pressure_systolic": (90, 140),
    "blood_pressure_diastolic": (60, 90),
    "body_temperature": (36.0, 37.5),
}

# A value that stays out of range is one situation, not one every six seconds.
# The family is told when a metric leaves its band, and at most this often
# while it stays out.
FLAG_COOLDOWN_SECONDS = 600

# What each scenario aims at. The value walks towards the target instead of
# jumping, so a trend line looks like a measurement rather than a step.
SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {
        "label": "Normal",
        "targets": {"hr": 74, "spo2": 97, "sys": 124, "dia": 79, "temp": 36.7},
        "steps_per_tick": 6,
    },
    "resting": {
        "label": "Resting",
        "targets": {"hr": 61, "spo2": 98, "sys": 117, "dia": 74, "temp": 36.5},
        "steps_per_tick": 0,
    },
    "walking": {
        "label": "Walking",
        "targets": {"hr": 104, "spo2": 96, "sys": 134, "dia": 83, "temp": 37.1},
        "steps_per_tick": 24,
    },
    "tachycardia": {
        "label": "Racing heart",
        "targets": {"hr": 142, "spo2": 94, "sys": 148, "dia": 92, "temp": 37.0},
        "steps_per_tick": 2,
    },
    "low_spo2": {
        "label": "Low oxygen",
        "targets": {"hr": 96, "spo2": 87, "sys": 126, "dia": 80, "temp": 36.8},
        "steps_per_tick": 1,
    },
    "fever": {
        "label": "Fever",
        "targets": {"hr": 99, "spo2": 96, "sys": 122, "dia": 78, "temp": 39.1},
        "steps_per_tick": 1,
    },
    "hypertension": {
        "label": "High blood pressure",
        "targets": {"hr": 84, "spo2": 97, "sys": 168, "dia": 104, "temp": 36.8},
        "steps_per_tick": 4,
    },
    "offline": {
        "label": "Not syncing",
        "targets": {"hr": 74, "spo2": 97, "sys": 124, "dia": 79, "temp": 36.7},
        "steps_per_tick": 0,
    },
}

RESET, DIM, RED, YELLOW, CYAN = (
    "\033[0m",
    "\033[2m",
    "\033[31m",
    "\033[33m",
    "\033[36m",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def is_unusual(metric: str, value: float) -> bool:
    band = BANDS.get(metric)
    return bool(band) and not (band[0] <= value <= band[1])


def band_reason(metric: str, value: float, unit: str) -> str:
    """The watch's own words for why it flagged a value."""
    low, high = BANDS[metric]
    if value > high:
        return f"Above the upper limit of {high:g} {unit} set on the watch."
    return f"Below the lower limit of {low:g} {unit} set on the watch."


class Watch:
    """One simulated device, paired by code to one running Parent App."""

    def __init__(self, index: int, subject: str, label: str, relay: str, interval: float):
        self.index = index
        # Doubles as the pairing code the relay and the Parent App both key
        # on. Never sent anywhere as a credential — the watch has none.
        self.subject = subject
        self.label = label
        self.relay = relay.rstrip("/")
        self.interval = interval

        self.lock = threading.Lock()
        self.paired = False
        self.person = ""
        self.scenario = "normal"
        self.paused = False
        self.tick = 0
        self.steps_today = 1200 + random.randint(0, 600)
        self.last_sync: str | None = None
        self.last_status = "starting"
        self.log: deque[dict[str, Any]] = deque(maxlen=40)

        targets = SCENARIOS["normal"]["targets"]
        self.values = {key: float(value) for key, value in targets.items()}
        # Manual overrides from the watch face, cleared when a scenario is set.
        self.manual: dict[str, float] = {}

        # Which metrics are currently outside their band, and when the family
        # was last told about each — so a long stretch out of range is one
        # notice rather than a stream of them.
        self.out_of_band: set[str] = set()
        self.flagged_at: dict[str, float] = {}
        self.flags_sent = 0

    # -- helpers ----------------------------------------------------------- #

    def say(self, message: str, color: str = "") -> None:
        print(f"{CYAN}{self.label}{RESET} {color}{message}{RESET}", flush=True)

    def note(self, text: str, kind: str = "info") -> None:
        with self.lock:
            self.log.appendleft({"at": now_iso(), "text": text, "kind": kind})

    def _relay(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        """Talk to the local watch relay — never the Gamira API directly.

        No credential travels with this: the relay is loopback-only and holds
        no account either. Everything the watch sends carries its pairing
        code, which is all a real BLE-paired watch with no login of its own
        would have to offer.
        """
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.relay}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8") or "null"
                return response.status, json.loads(body)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            try:
                return error.code, json.loads(body)
            except json.JSONDecodeError:
                return error.code, {"error": {"message": body[:200]}}
        except (urllib.error.URLError, TimeoutError) as error:
            return 0, {"error": {"message": str(error)}}

    # -- pairing ----------------------------------------------------------- #

    def pair(self, deadline_seconds: float = 45.0) -> bool:
        """Wait for a running Parent App to claim this watch's pairing code.

        The watch never learns a senior id or an account — only whether *some*
        Parent App has registered itself under the same code, and the name it
        gave itself while doing so.
        """
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            status, body = self._relay(
                "GET", f"/pair-status?code={urllib.parse.quote(self.subject)}"
            )
            if status == 200 and (body or {}).get("paired"):
                self.paired = True
                self.person = body.get("person") or "Unknown"
                self.last_status = "paired"
                self.say(f"paired with {self.person}", DIM)
                self.note(f"Paired with {self.person}")
                return True
            time.sleep(1.0)
        self.last_status = "no Parent App has claimed this pairing code"
        self.say(f"nobody claimed pairing code '{self.subject}'", RED)
        return False

    # -- simulation -------------------------------------------------------- #

    def _drift(self) -> None:
        """Walk each value towards its target with a little noise."""
        targets = dict(SCENARIOS[self.scenario]["targets"])
        targets.update(self.manual)
        for key, target in targets.items():
            current = self.values[key]
            step = (target - current) * 0.45
            # Per-metric jitter. Small enough that a scenario inside the band
            # stays inside it: noise alone must never look like a real change,
            # or every flag becomes noise the family learns to ignore.
            noise = {
                "temp": random.uniform(-0.15, 0.15),
                "spo2": random.uniform(-0.6, 0.6),
            }.get(key, random.uniform(-2, 2))
            self.values[key] = round(current + step + noise, 2)

        if not self.paused and self.scenario != "offline":
            self.steps_today += SCENARIOS[self.scenario]["steps_per_tick"]

    def reading_set(self) -> dict[str, float]:
        """Current values as API metric names."""
        return {
            "heart_rate": round(self.values["hr"]),
            "oxygen_saturation": min(100, round(self.values["spo2"])),
            "blood_pressure_systolic": round(self.values["sys"]),
            "blood_pressure_diastolic": round(self.values["dia"]),
            "body_temperature": round(self.values["temp"], 1),
            "steps": float(self.steps_today),
        }

    def _due_metrics(self, force: bool) -> list[str]:
        if force:
            return list(METRICS)
        return [
            metric for metric, (_, _, every) in METRICS.items() if self.tick % every == 0
        ]

    def send(self, force: bool = False) -> None:
        if not self.paired:
            return

        readings = self.reading_set()
        measured_at = now_iso()
        due = self._due_metrics(force)
        sent, failed, unusual = 0, 0, []
        out: dict[str, tuple[float, str]] = {}

        for metric in due:
            unit = METRICS[metric][0]
            value = readings[metric]
            flagged = is_unusual(metric, value)
            # Handed to the relay, not the API: the real HealthReading row (and
            # its id) is created later, by the Parent App, when it drains this
            # and forwards it under its own session.
            status, body = self._relay(
                "POST",
                "/ingest/readings",
                {
                    "pairing_code": self.subject,
                    "reading": {
                        "metric": metric,
                        "value": value,
                        "unit": unit,
                        "source": "device",
                        "source_device": f"Gamira Watch (sim) · {self.label}",
                        "measured_at": measured_at,
                        # The reading carries the device's own note, so the
                        # value is never shown without the reason it was
                        # singled out.
                        "note": band_reason(metric, value, unit) if flagged else None,
                    },
                },
            )
            if status == 202:
                sent += 1
                if flagged:
                    unusual.append(f"{metric.replace('_', ' ')} {value:g}{unit}")
                    out[metric] = (value, unit)
            else:
                failed += 1
                message = (body or {}).get("error", {}).get("message", f"HTTP {status}")
                self.last_status = f"rejected: {message}"
                self.note(f"{metric}: {message}", "error")

        self._tell_family(due, out, measured_at)

        with self.lock:
            self.last_sync = measured_at
            if failed == 0:
                self.last_status = "unusual readings sent" if unusual else "sending"

        summary = (
            f"HR {readings['heart_rate']:.0f} bpm · "
            f"SpO2 {readings['oxygen_saturation']:.0f}% · "
            f"BP {readings['blood_pressure_systolic']:.0f}/"
            f"{readings['blood_pressure_diastolic']:.0f} · "
            f"{readings['body_temperature']:.1f}C · "
            f"{readings['steps']:.0f} steps"
        )
        if failed:
            self.say(f"{summary} — {failed} rejected", RED)
        elif unusual:
            self.say(f"{summary}  UNUSUAL: {', '.join(unusual)}", YELLOW)
            self.note(f"Unusual: {', '.join(unusual)}", "unusual")
        else:
            self.say(f"{summary} → {sent} recorded", DIM)

    def _tell_family(
        self,
        evaluated: list[str],
        out: dict[str, tuple[float, str]],
        measured_at: str,
    ) -> None:
        """Hand a device flag to the relay when a metric leaves its band, and
        not again.

        Deliberately not an SOS. The family sees a notice attributed to this
        watch; nobody is called, and Gamira does not add an opinion. This does
        not know whether the family was actually told — that answer comes
        back from the real API, once the Parent App has forwarded it — only
        that the relay accepted it for delivery.
        """
        now = time.monotonic()
        for metric, (value, unit) in out.items():
            entered = metric not in self.out_of_band
            stale = now - self.flagged_at.get(metric, 0.0) > FLAG_COOLDOWN_SECONDS
            if not (entered or stale):
                continue

            reason = band_reason(metric, value, unit)
            status, body = self._relay(
                "POST",
                "/ingest/device-flags",
                {
                    "pairing_code": self.subject,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "reason": reason,
                    # Short on purpose: this name is read inside a sentence in
                    # the family's notification.
                    "source_device": self.label,
                    "measured_at": measured_at,
                },
            )
            if status == 202:
                self.flagged_at[metric] = now
                self.flags_sent += 1
                self.say(
                    f"FLAGGED {metric.replace('_', ' ')} {value:g}{unit} — "
                    "handed to the phone",
                    YELLOW,
                )
                self.note(f"Flagged {metric.replace('_', ' ')} {value:g}{unit}", "unusual")
            else:
                message = (body or {}).get("error", {}).get("message", f"HTTP {status}")
                self.note(f"flag rejected: {message}", "error")
                # Back off exactly as a success would. Without this a rejected
                # flag was retried on every tick for as long as the value
                # stayed outside the band — `entered` is false by then and
                # `stale` is true against a timestamp that was never set — so
                # one broken endpoint became a request every few seconds,
                # each one a full traceback in the console. That is what a
                # failing server looks like from here, and hammering it is the
                # one thing a client must not do about it.
                self.flagged_at[metric] = now

        # Only metrics measured this tick can be said to have returned to
        # range; the others keep whatever state they had.
        self.out_of_band = (self.out_of_band - set(evaluated)) | set(out)

    def raise_sos(self, note: str | None = None) -> tuple[int, Any]:
        if not self.paired:
            return 0, {"error": {"message": "not paired"}}
        status, body = self._relay(
            "POST",
            "/ingest/sos",
            {"pairing_code": self.subject, "source": "watch", "note": note or None},
        )
        if status == 202:
            self.say("SOS RAISED — handed to the phone to alert the family", RED)
            self.note("SOS raised · handed to the phone", "sos")
        else:
            message = (body or {}).get("error", {}).get("message", f"HTTP {status}")
            self.say(f"SOS failed: {message}", RED)
            self.note(f"SOS failed: {message}", "error")
        return status, body

    def run(self) -> None:
        if not self.pair():
            return
        self.send(force=True)
        while True:
            time.sleep(self.interval)
            self.tick += 1
            self._drift()
            if self.paused or self.scenario == "offline":
                with self.lock:
                    self.last_status = (
                        "paused" if self.paused else "not syncing (offline)"
                    )
                continue
            self.send()

    # -- state for the watch face ------------------------------------------ #

    def snapshot(self) -> dict[str, Any]:
        readings = self.reading_set()
        with self.lock:
            return {
                "index": self.index,
                "label": self.label,
                "subject": self.subject,
                "person": self.person,
                "paired": self.paired,
                "scenario": self.scenario,
                "scenario_label": SCENARIOS[self.scenario]["label"],
                "paused": self.paused,
                "interval": self.interval,
                "last_sync": self.last_sync,
                "status": self.last_status,
                "readings": readings,
                "unusual": {
                    metric: is_unusual(metric, value)
                    for metric, value in readings.items()
                },
                "bands": BANDS,
                "flags_sent": self.flags_sent,
                "log": list(self.log)[:12],
            }

    def control(self, payload: dict[str, Any]) -> None:
        scenario = payload.get("scenario")
        if scenario in SCENARIOS:
            with self.lock:
                self.scenario = scenario
                self.manual.clear()
            self.note(f"Scenario: {SCENARIOS[scenario]['label']}")
        for key, name in (("hr", "heart rate"), ("spo2", "oxygen"), ("temp", "temp")):
            if key in payload:
                with self.lock:
                    self.manual[key] = float(payload[key])
                self.note(f"Set {name} to {payload[key]:g}")
        if "paused" in payload:
            with self.lock:
                self.paused = bool(payload["paused"])
            self.note("Paused" if self.paused else "Resumed")
        if "interval" in payload:
            with self.lock:
                self.interval = max(1.0, float(payload["interval"]))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    watches: list[Watch] = []

    def log_message(self, *args: Any) -> None:  # noqa: A003 - silence access log
        """The face polls once a second; its own log would drown the sim's."""

    def handle_one_request(self) -> None:
        """A closed watch face is not an error worth ten lines about.

        The face polls once a second, so closing its window — or the console
        shutting the whole stack down — resets a connection mid-request, and the
        stdlib prints a full traceback for it. That went into the runner's log,
        which is where somebody is trying to read what the shutdown did.
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

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _watch(self, payload: dict[str, Any]) -> Watch | None:
        try:
            return self.watches[int(payload.get("index", 0))]
        except (ValueError, IndexError):
            return None

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            page = (HERE / "watch.html").read_bytes()
            self._send(200, page, "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(200, {"watches": [watch.snapshot() for watch in self.watches]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        watch = self._watch(payload)
        if watch is None:
            self._json(404, {"error": "no such watch"})
            return

        path = self.path.split("?")[0]
        if path == "/api/control":
            watch.control(payload)
            self._json(200, watch.snapshot())
        elif path == "/api/send-now":
            threading.Thread(target=lambda: watch.send(force=True), daemon=True).start()
            self._json(202, {"ok": True})
        elif path == "/api/sos":
            status, body = watch.raise_sos(payload.get("note"))
            self._json(200 if status == 202 else 502, body)
        else:
            self._json(404, {"error": "not found"})


def parse_pairs(values: list[str]) -> list[tuple[str, str]]:
    pairs = []
    for entry in values:
        subject, _, label = entry.partition("=")
        pairs.append((subject.strip(), label.strip() or f"{subject.strip()}'s watch"))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulated Gamira watch")
    parser.add_argument(
        "--relay",
        default="http://127.0.0.1:8021",
        help="The watch relay's own address (see watch_relay_server.py) — "
        "never the Gamira API; the watch has no account to call it with.",
    )
    parser.add_argument("--port", type=int, default=8020)
    # 0.0.0.0 only when the runner is set up for phone testing: this face can
    # write readings and raise an SOS for the person it is paired to.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--interval", type=float, default=6.0)
    parser.add_argument(
        "--pair",
        action="append",
        default=[],
        metavar="CODE=LABEL",
        help="A pairing code this watch wears, e.g. sharma-senior=Dad's watch. "
        "Matched against whichever Parent App registers under the same code.",
    )
    args = parser.parse_args()

    pairs = parse_pairs(args.pair) or [("sharma-senior", "Dad's watch")]
    watches = [
        Watch(index, subject, label, args.relay, args.interval)
        for index, (subject, label) in enumerate(pairs)
    ]
    Handler.watches = watches

    for watch in watches:
        threading.Thread(target=watch.run, daemon=True).start()

    print(f"watch face  http://localhost:{args.port}/", flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
