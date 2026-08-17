"""Start the whole of Gamira, in one command.

    python run.py                       one parent, one dashboard, one watch
    python run.py --parents 2 --watches 2
    python run.py --dashboards 2 --no-voice
    run.cmd                             same thing, double-clickable

What comes up:

    watch sim  ──►  Gamira API (FastAPI, SQLite)  ──►  Parent App    (phone window)
                                                  ──►  Family Dash   (phone window)
    Gemini Live token server  ──►  Parent App voice

Each app opens in its own phone-sized window with its own browser profile, so
two Parent Apps can be two different people at the same time. This terminal is
the server: every request the API handles is printed here, and an SOS is hard
to miss.

Everything worth changing is in the CONFIG block below, and the counts can be
overridden per run with the flags above. Ctrl+C stops all of it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# CONFIG — the knobs
# --------------------------------------------------------------------------- #

# Port 8000 is deliberately avoided: it is busy on this machine.
API_PORT = 8010
PARENT_PORT = 5173
DASHBOARD_PORT = 5174
WATCH_PORT = 8020
VOICE_PORT = 8787
CONSOLE_PORT = 8030

# How many windows to open. Override per run with --parents / --dashboards /
# --watches. Each entry is taken from the rosters below, in order.
COUNTS = {"parents": 1, "dashboards": 1, "watches": 1}

# Who each window signs in as. These are the seeded development identities
# (`dev:<subject>`); add a row here and to app/db/seed.py to grow the cast.
PARENTS = [
    ("sharma-senior", "Dad · Vikram"),
    ("sharma-senior-2", "Mum · Sunita"),
]
DASHBOARDS = [
    ("sharma-owner", "Anjali · owner"),
    ("sharma-caregiver", "Rohan · caregiver"),
    # A family that shares nothing with the Sharmas — useful for checking that
    # an SOS and a watch reading stay inside one family.
    ("iyer-owner", "Meera · another family"),
]
# Each watch is worn by the person whose account it signs in as.
WATCHES = [
    ("sharma-senior", "Dad's watch"),
    ("sharma-senior-2", "Mum's watch"),
]

PHONE_SIZE = (400, 860)  # the app windows
WATCH_SIZE = (380, 700)  # the simulator windows
CONSOLE_SIZE = (1140, 860)  # the server console window
WINDOW_GAP = 16

# The server console: the same logs as this terminal, plus the controls and the
# database browser. Set to False to run with the terminal alone.
CONSOLE = True

# How often the app screens re-read the record. Gamira has no push delivery
# yet, so this is what makes a watch reading or a dose appear "live".
POLL_MS = 5000
WATCH_INTERVAL_SECONDS = 6.0

VOICE = True  # start the Gemini Live token server alongside the Parent App
OPEN_WINDOWS = True
API_RELOAD = True  # uvicorn --reload: edit the backend and it restarts

# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "gamira-backend"
PARENT_APP = ROOT / "gamira-parent-app-original"
DASHBOARD = ROOT / "gamira-family-dashboard"
WATCH_SIM = ROOT / "tools" / "watch-sim"

# The system monitor lives in tools/, so it is importable without installing
# anything. It watches the machine, not the API — see tools/sysmon.py for why.
sys.path.insert(0, str(ROOT / "tools"))
try:
    from sysmon import SystemMonitor
except Exception:  # pragma: no cover - a monitor must never block a start
    SystemMonitor = None
CONSOLE_DIR = ROOT / "tools" / "console"
PROFILES = Path(tempfile.gettempdir()) / "gamira-run-profiles"

IS_WINDOWS = platform.system() == "Windows"

# Vite prints "➜" in its banner, which a cp1252 console cannot encode — and an
# unhandled UnicodeEncodeError in an output thread would take the pump down.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLORS = {
    "run": "\033[32m",
    "api": "\033[34m",
    "parent": "\033[36m",
    "dash": "\033[35m",
    "watch": "\033[33m",
    "voice": "\033[95m",
    "db": "\033[90m",
    "err": "\033[31m",
}

processes: list[tuple[str, subprocess.Popen]] = []
browsers: list[subprocess.Popen] = []
shutting_down = threading.Event()
KILL_JOB = None  # set in main(); see open_kill_job()

# Every child that can be restarted, by tag: the arguments spawn() was called
# with, so the console can bring one back without restarting the whole stack.
SPECS: dict[str, dict] = {}
# PIDs this runner killed itself. Their output pump must not report them as a
# crash on the way out.
STOPPED_ON_PURPOSE: set[int] = set()

ANSI = re.compile(r"\x1b\[[0-9;]*m")
REQUEST_LINE = re.compile(
    r"^\d\d:\d\d:\d\d +(?P<method>GET|POST|PATCH|PUT|DELETE) +(?P<path>\S+) +(?P<status>\d{3})"
)


def classify(text: str) -> str:
    """Label a line so the console can filter by what it means, not by words."""
    if "SOS" in text:
        return "sos"
    if "UNUSUAL" in text:
        return "unusual"
    match = REQUEST_LINE.match(text)
    if match:
        if int(match.group("status")) >= 400:
            return "error"
        return "read" if match.group("method") == "GET" else "write"
    lowered = text.lower()
    if any(word in lowered for word in ("error", "traceback", "exited with code")):
        return "error"
    return "info"


class LogBus:
    """Every line this runner prints, kept so the console window can show it.

    A ring buffer rather than a file: this is a development view of what just
    happened, and nothing here is the audit trail — that lives in the API.
    """

    def __init__(self, capacity: int = 6000) -> None:
        self.lock = threading.Lock()
        self.entries: deque[dict] = deque(maxlen=capacity)
        self.seq = 0

    def add(self, tag: str, text: str, meta: dict | None = None) -> None:
        plain = ANSI.sub("", text).rstrip()
        if not plain:
            return
        with self.lock:
            self.seq += 1
            entry = {
                "seq": self.seq,
                "at": time.strftime("%H:%M:%S"),
                "t": time.time(),
                "tag": tag,
                "text": plain,
                "kind": classify(plain),
            }
            # Requests carry their id, so the console can pivot from a line to
            # everything else that happened inside the same request.
            if meta:
                entry.update(meta)
            self.entries.append(entry)

    def after(self, seq: int, limit: int = 900) -> list[dict]:
        with self.lock:
            return [entry for entry in self.entries if entry["seq"] > seq][-limit:]

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()


class RequestBus:
    """Completed API requests, kept for the console's request inspector.

    The API already logs every request; this is the same information kept as
    numbers instead of prose, so the console can sort, group and time it.
    """

    def __init__(self, capacity: int = 3000) -> None:
        self.lock = threading.Lock()
        self.entries: deque[dict] = deque(maxlen=capacity)
        self.seq = 0

    def add(self, fields: dict) -> dict:
        with self.lock:
            self.seq += 1
            entry = {"seq": self.seq, "at": time.strftime("%H:%M:%S"), **fields}
            self.entries.append(entry)
            return entry

    def recent(self, limit: int = 400) -> list[dict]:
        with self.lock:
            return list(self.entries)[-limit:]

    def stats(self) -> list[dict]:
        """Per-endpoint timing, with ids collapsed so one route is one row."""
        with self.lock:
            entries = list(self.entries)

        grouped: dict[tuple[str, str], list[dict]] = {}
        for entry in entries:
            key = (entry["method"], entry["template"])
            grouped.setdefault(key, []).append(entry)

        rows = []
        for (method, template), calls in grouped.items():
            times = sorted(call["ms"] for call in calls)
            rows.append(
                {
                    "method": method,
                    "template": template,
                    "count": len(calls),
                    "errors": sum(1 for call in calls if call["status"] >= 400),
                    "p50": _percentile(times, 0.50),
                    "p95": _percentile(times, 0.95),
                    "max": times[-1] if times else 0,
                }
            )
        rows.sort(key=lambda row: row["count"], reverse=True)
        return rows

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 2)


LOGS = LogBus()
REQUESTS = RequestBus()


def say(message: str, tag: str = "run", color: str | None = None) -> None:
    paint = COLORS.get(color or tag, "")
    print(f"{paint}[{tag}]{RESET} {message}", flush=True)
    LOGS.add(tag, message)


def fail(message: str) -> None:
    say(message, "run", "err")


# --------------------------------------------------------------------------- #
# Ports and processes
# --------------------------------------------------------------------------- #


def open_kill_job():
    """A Windows job object whose children die when this process does.

    Ctrl+C is handled below, but a crash or a `taskkill` on this window would
    otherwise leave uvicorn and two Vite servers holding their ports, and the
    next `run.py` would refuse to start.
    """
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount",
                         "OtherOperationCount", "ReadTransferCount",
                         "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(wintypes.ULONG)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = ctypes.windll.kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ctypes.windll.kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        return job
    except Exception:
        return None


def adopt(job, process: subprocess.Popen) -> None:
    if job is None:
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, process.pid)
        if handle:
            ctypes.windll.kernel32.AssignProcessToJobObject(job, handle)
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass  # best effort; Ctrl+C shutdown still stops everything


def port_in_use(port: int) -> bool:
    # Check both stacks: on Windows "localhost" resolves to ::1 first, so a
    # server already holding the port is invisible to an IPv4-only probe.
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.4)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def wait_for_port(port: int, what: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if shutting_down.is_set():
            return False
        if port_in_use(port):
            return True
        time.sleep(0.25)
    fail(f"{what} did not come up on port {port} within {timeout:.0f}s.")
    return False


def pump(process: subprocess.Popen, tag: str, render) -> None:
    """Stream a child's output through this terminal, one prefixed line at a time."""
    color = COLORS.get(tag, "")
    try:
        for raw in process.stdout:  # type: ignore[union-attr]
            text = raw.rstrip()
            if not text:
                continue
            lines, meta = render(text) if render else ([text], None)
            for line in lines or []:
                print(f"{color}[{tag}]{RESET} {line}", flush=True)
                LOGS.add(tag, line, meta)
    except Exception as error:  # never let a print failure kill the pump
        fail(f"{tag} output stopped: {error}")
    process.wait()  # otherwise returncode is still None right after EOF
    if shutting_down.is_set() or process.pid in STOPPED_ON_PURPOSE:
        return
    fail(f"{tag} exited with code {process.returncode}")
    # The API, worker, watch and voice can be brought back from the console.
    # Losing an app dev server means its windows are dead, so the stack comes
    # down rather than leaving windows that quietly show nothing.
    if tag in ("api", "worker", "watch", "voice"):
        say("  bring it back with Restart in the server console.")
    else:
        stop_all()


def spawn(tag: str, command: list[str], cwd: Path, env: dict | None = None, render=None):
    SPECS[tag] = {"command": command, "cwd": cwd, "env": env, "render": render}
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        # Keeps Ctrl+C in this console from reaching the children directly, so
        # they can be shut down in order instead of racing them.
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    processes.append((tag, process))
    SPECS[tag]["process"] = process
    adopt(KILL_JOB, process)
    threading.Thread(target=pump, args=(process, tag, render), daemon=True).start()
    return process


def running(tag: str) -> bool:
    process = SPECS.get(tag, {}).get("process")
    return bool(process) and process.poll() is None


def restart(tag: str) -> str:
    """Stop one service and start it again from the arguments it was given."""
    spec = SPECS.get(tag)
    if spec is None:
        return f"{tag} is not part of this run"
    process = spec.get("process")
    if process is not None and process.poll() is None:
        kill(process)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
    processes[:] = [(name, proc) for name, proc in processes if proc is not process]
    say(f"restarting {tag}…")
    spawn(tag, spec["command"], spec["cwd"], spec["env"], spec["render"])
    return f"{tag} restarted"


def kill(process: subprocess.Popen) -> None:
    STOPPED_ON_PURPOSE.add(process.pid)
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        # npm spawns node as a grandchild, and uvicorn --reload spawns a worker;
        # terminate() would only kill the shim and leave the port held.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True
        )
    else:
        process.terminate()


def find_orphans() -> list[dict]:
    """Gamira processes from an earlier run that nobody is supervising.

    The failure this prevents is specific and it happened: uvicorn and the
    worker were started repeatedly without the previous ones dying, so several
    workers polled the same SQLite file once a second each, every one of them
    holding a write lock in turn. The machine had no idea anything was wrong —
    it just got slower, and eventually fell over.

    Matched on the command line rather than the process name, because
    `python.exe` on its own says nothing.
    """
    if os.name != "nt":
        return []
    ours = {os.getpid()}
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='node.exe'\" | "
        "Where-Object { $_.CommandLine -and ("
        "$_.CommandLine -like '*app.worker*' -or "
        "$_.CommandLine -like '*uvicorn app.main*' -or "
        "$_.CommandLine -like '*gemini_token_server*' -or "
        "$_.CommandLine -like '*sim_server.py*') } | "
        "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"
    )
    try:
        output = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    found = []
    for line in output.splitlines():
        pid_text, _, command = line.partition("|")
        try:
            pid = int(pid_text.strip())
        except ValueError:
            continue
        if pid in ours:
            continue
        if "app.worker" in command:
            kind = "worker"
        elif "uvicorn app.main" in command:
            kind = "api"
        elif "gemini_token_server" in command:
            kind = "voice lab"
        else:
            kind = "watch"
        found.append({"pid": pid, "kind": kind, "command": command.strip()[:120]})
    return found


def reap_orphans() -> int:
    """Stop leftover Gamira processes before starting new ones.

    Deliberately narrow: only processes whose command line is unmistakably one
    of ours. It will not touch an unrelated python.
    """
    orphans = find_orphans()
    if not orphans:
        return 0
    say(f"found {len(orphans)} leftover Gamira process(es) from an earlier run:")
    for orphan in orphans:
        say(f"  {orphan['kind']} pid {orphan['pid']}")
    killed = 0
    for orphan in orphans:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(orphan["pid"])],
                capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            killed += 1
        except (OSError, subprocess.SubprocessError):
            fail(f"could not stop pid {orphan['pid']} — stop it by hand")
    if killed:
        say(f"stopped {killed}; starting clean")
    return killed


def check_machine_headroom() -> bool:
    """Refuse to start on a machine that is already struggling.

    Starting an API, a worker, two Vite servers and several browser windows on a
    machine with no memory or no disk left is how a slow afternoon becomes an
    unclean shutdown. Warn loudly, and stop only when it is genuinely unsafe.
    """
    if SystemMonitor is None:
        return True
    try:
        snapshot = SystemMonitor(interval_seconds=1.0).snapshot()
    except Exception:
        return True
    if not snapshot.get("available"):
        return True

    ok = True
    free_gb = snapshot.get("disk_free_gb")
    memory = snapshot.get("memory_percent")

    if free_gb is not None and free_gb < 5:
        fail(
            f"only {free_gb:.0f} GB free on {snapshot.get('disk_path')} — "
            "Windows needs room for the page file and temp files."
        )
        say("  free some space, or run with --force to start anyway.")
        ok = False
    elif free_gb is not None and free_gb < 20:
        fail(
            f"{free_gb:.0f} GB free on {snapshot.get('disk_path')}. "
            "The Health tab will keep an eye on it."
        )

    if memory is not None and memory >= 92:
        fail(
            f"memory is already {memory:.0f}% full before starting anything. "
            "Close something first, or run with --force."
        )
        ok = False
    elif memory is not None and memory >= 85:
        fail(f"memory is {memory:.0f}% full — expect this to be slow.")

    if snapshot.get("throttled"):
        fail(
            "Windows is currently limiting this CPU's speed (usually heat). "
            "Everything will be slow until it cools down."
        )
    return ok


def stop_all() -> None:
    if shutting_down.is_set():
        return
    shutting_down.set()
    for process in browsers:
        kill(process)
    for tag, process in processes:
        if process.poll() is None:
            say(f"stopping {tag}…")
        kill(process)
    for _, process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    # A supervised process can still leave a grandchild behind — npm spawns
    # node, and a killed parent does not always take it with it. Sweeping here
    # is what stops the next run inheriting a busy machine.
    remaining = find_orphans()
    for orphan in remaining:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(orphan["pid"])],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            pass


# --------------------------------------------------------------------------- #
# Reading the API's log back out
# --------------------------------------------------------------------------- #

ACCESS_LINE = re.compile(
    r"^(?P<date>[\d-]+) (?P<time>[\d:]+),\d+ +(?P<level>\w+) +"
    r"(?P<logger>\S+) \[(?P<request_id>[^\]]*)\] (?P<rest>.*)$"
)
KEY_VALUE = re.compile(r"(\w+)=(\S+)")
UUID_IN_PATH = re.compile(
    r"([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

STATUS_COLOR = {2: "\033[32m", 3: "\033[36m", 4: "\033[33m", 5: "\033[31m"}


def shorten(path: str) -> str:
    """`/seniors/7f3a2b91-…-9c/doses` reads better as `/seniors/7f3a2b91…/doses`."""
    return UUID_IN_PATH.sub(r"\1…", path)


def describe(method: str, path: str, status: int) -> str | None:
    """A plain-language note for the requests that matter in a demo."""
    if method == "POST" and path.endswith("/sos") and status == 201:
        return "SOS raised — every other family member now sees it in their app"
    if method == "POST" and path.endswith("/device-flags") and status == 201:
        return "a watch flagged a reading — the family sees a notice, not an alarm"
    if method == "POST" and path.endswith("/health-readings") and status == 201:
        return "a reading was recorded (watch or family entry)"
    if method == "POST" and path.endswith("/taken"):
        return "a dose was confirmed as taken"
    if method == "POST" and path.endswith("/skipped"):
        return "a dose was recorded as skipped"
    if method == "POST" and path.endswith("/opened"):
        return "an alert was acknowledged"
    return None


def endpoint_template(path: str) -> str:
    """`/seniors/7f3a…/doses` and its neighbours are one endpoint, not many."""
    return UUID_IN_PATH.sub(":id", path)


def render_api(text: str) -> tuple[list[str], dict | None]:
    """Turn one API log line into what the terminal shows and what we keep."""
    match = ACCESS_LINE.match(text)
    if not match:
        # Tracebacks and anything else that is not one of our log lines.
        colour = COLORS["err"] if ("ERROR" in text or "Traceback" in text) else DIM
        return [f"{colour}{text}{RESET}"], None

    logger, rest, clock = (
        match.group("logger"),
        match.group("rest"),
        match.group("time"),
    )
    # uvicorn logs its own version of every request. Ours carries the timing
    # and the request id, so printing both would just halve the readability.
    if logger == "uvicorn.access":
        return [], None

    fields = dict(KEY_VALUE.findall(rest))
    request_id = match.group("request_id") or ""
    if not rest.startswith(("request_completed", "request_failed")):
        colour = COLORS["err"] if match.group("level") in ("ERROR", "CRITICAL") else DIM
        meta = {"request_id": request_id} if request_id else None
        return [f"{colour}{clock} {rest}{RESET}".rstrip()], meta

    method = fields.get("method", "?")
    raw_path = fields.get("path", "?")
    path = shorten(raw_path)
    status = int(fields.get("status_code", "0") or 0)
    duration = fields.get("duration_ms", "?")
    colour = STATUS_COLOR.get(status // 100, COLORS["err"])
    # A screen polling for changes should not shout as loudly as a write.
    verb = f"{DIM}{method:<6}{RESET}" if method == "GET" and status < 400 else f"{method:<6}"

    try:
        milliseconds = float(duration)
    except ValueError:
        milliseconds = 0.0

    REQUESTS.add(
        {
            "method": method,
            "path": raw_path,
            "short": path,
            "template": endpoint_template(raw_path),
            "status": status,
            "ms": milliseconds,
            "request_id": request_id,
        }
    )

    line = (
        f"{DIM}{clock}{RESET} {verb}{path:<44} "
        f"{colour}{status}{RESET} {DIM}{duration}ms{RESET}"
    )
    lines = [line]

    note = describe(method, raw_path, status)
    if note:
        highlight = COLORS["err"] + BOLD if "SOS" in note else COLORS["run"]
        lines.append(f"        {highlight}└─ {note}{RESET}")
    return lines, {"request_id": request_id, "status": status, "ms": milliseconds}


# --------------------------------------------------------------------------- #
# Browser windows
# --------------------------------------------------------------------------- #

CHROMIUM_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
]


def find_browser() -> str | None:
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def screen_width(default: int = 1920) -> int:
    if not IS_WINDOWS:
        return default
    try:
        import ctypes

        return int(ctypes.windll.user32.GetSystemMetrics(0)) or default
    except Exception:
        return default


def open_window(
    browser: str | None,
    url: str,
    name: str,
    size: tuple[int, int],
    slot,
    insecure: bool = False,
):
    """One app window, in its own browser profile.

    The separate profile is the point: two Parent App windows served by one dev
    server would otherwise share a localStorage token and be the same person.
    """
    if browser is None:
        import webbrowser

        webbrowser.open(url)
        return

    profile = PROFILES / name
    profile.mkdir(parents=True, exist_ok=True)
    width, height = size
    x, y = slot
    flags = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        f"--window-position={x},{y}",
        "--no-first-run",
        "--no-default-browser-check",
        # The dashboard's SOS alert makes a sound; without this the browser
        # would swallow it until the window had been clicked.
        "--autoplay-policy=no-user-gesture-required",
    ]
    if insecure:
        # Only when --phone generated a self-signed certificate, and only for
        # these throwaway profiles, which never visit anything but this stack.
        # It saves clicking through a warning in every desktop window; the
        # phone still asks once, as it should.
        flags.append("--ignore-certificate-errors")
    process = subprocess.Popen(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browsers.append(process)


class Tiler:
    """Lays windows out left to right, wrapping at the edge of the screen."""

    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.row_height = 0
        self.width = screen_width()

    def place(self, size: tuple[int, int]) -> tuple[int, int]:
        width, height = size
        if self.x + width > self.width:
            # Next row. Windows taller than the screen still overlap, but they
            # are draggable — a window placed off-screen would not be.
            self.x = 0
            self.y = min(self.y + self.row_height + WINDOW_GAP, 200)
            self.row_height = 0
        slot = (self.x, self.y)
        self.x += width + WINDOW_GAP
        self.row_height = max(self.row_height, height)
        return slot

    def place_wide(self, size: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        """A window that wants the rest of the row, or a new row if it is thin.

        The console is the one window that benefits from every pixel of width,
        so it takes whatever the phone-shaped windows left behind.
        """
        remaining = self.width - self.x - 8
        if remaining >= 560:
            slot = (self.x, self.y)
            height = max(self.row_height, size[1]) if self.row_height else size[1]
            self.x += remaining + WINDOW_GAP
            return slot, (remaining, height)
        return self.place(size), size


# --------------------------------------------------------------------------- #
# Testing on a phone
# --------------------------------------------------------------------------- #


def lan_address() -> str | None:
    """This machine's address on the local network.

    Connecting a UDP socket to an outside address makes the OS pick the
    interface it would actually route through; nothing is sent.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.4)
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
    except OSError:
        return None


# A page only gets the microphone on a secure origin, and http://192.168.x.x is
# not one — so phone testing of the Live API needs a certificate. It is
# self-signed, which is why the phone asks once before trusting it.
CERT_SCRIPT = """
import datetime, ipaddress, sys
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

directory, host = Path(sys.argv[1]), sys.argv[2]
directory.mkdir(parents=True, exist_ok=True)
key_path, cert_path = directory / "gamira-key.pem", directory / "gamira-cert.pem"

names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
try:
    names.append(x509.IPAddress(ipaddress.ip_address(host)))
except ValueError:
    names.append(x509.DNSName(host))

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Gamira local development")])
now = datetime.datetime.now(datetime.timezone.utc)
certificate = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(subject)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=60))
    .add_extension(x509.SubjectAlternativeName(names), critical=False)
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .sign(key, hashes.SHA256())
)
key_path.write_bytes(
    key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
)
cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
print(cert_path)
print(key_path)
"""

QR_SCRIPT = """
import json, sys
import qrcode
import qrcode.image.svg

out = {}
for url in json.load(sys.stdin):
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    out[url] = image.to_string(encoding="unicode")
print(json.dumps(out))
"""


def make_certificate(python: str, host: str) -> tuple[str, str] | None:
    """A certificate for localhost and this machine's LAN address.

    Generated with `cryptography`, which the backend venv already has through
    PyJWT[crypto], so this adds no dependency. Reused while it exists.
    """
    directory = Path(tempfile.gettempdir()) / "gamira-run-tls"
    cert, key = directory / "gamira-cert.pem", directory / "gamira-key.pem"
    marker = directory / "host.txt"
    if cert.is_file() and key.is_file() and marker.is_file():
        if marker.read_text(encoding="utf-8").strip() == host:
            return str(cert), str(key)

    result = subprocess.run(
        [python, "-c", CERT_SCRIPT, str(directory), host], capture_output=True, text=True
    )
    if result.returncode != 0 or not cert.is_file():
        fail("could not generate a certificate for phone testing:")
        say(f"  {(result.stderr or '').strip().splitlines()[-1:] or ''}")
        return None
    marker.write_text(host, encoding="utf-8")
    return str(cert), str(key)


def make_qr_codes(python: str, urls: list[str]) -> dict[str, str]:
    """QR codes as inline SVG, one per URL. Empty if `qrcode` cannot be had."""
    if not urls:
        return {}
    probe = subprocess.run([python, "-c", "import qrcode"], capture_output=True)
    if probe.returncode != 0:
        say("installing qrcode for the phone tab (one time)…")
        if subprocess.run(
            [python, "-m", "pip", "install", "--quiet", "qrcode"]
        ).returncode != 0:
            fail("could not install qrcode — the phone tab will show plain links.")
            return {}
    result = subprocess.run(
        [python, "-c", QR_SCRIPT],
        input=json.dumps(urls),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail("could not render QR codes — the phone tab will show plain links.")
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------- #
# The server console
# --------------------------------------------------------------------------- #

SAFE_QUERY = re.compile(r"^\s*(select|with)\b", re.I)


def sqlite_file() -> Path | None:
    """The local database file, when the backend is running on SQLite."""
    url = os.environ.get("DATABASE_URL") or load_dotenv(BACKEND / ".env").get(
        "DATABASE_URL", ""
    )
    if "sqlite" not in url:
        return None
    tail = url.split("///")[-1]
    return (BACKEND / tail).resolve() if tail.startswith(".") else Path(tail)


def read_only_db() -> sqlite3.Connection:
    """Open the API's database without being able to change it.

    The console is a window onto the data, not a second writer: a manager that
    could edit rows behind the API would let a demo produce states the real
    rules forbid.
    """
    path = sqlite_file()
    if path is None or not path.is_file():
        raise FileNotFoundError("No local SQLite database for this run.")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


class Console:
    """State and actions the console window can see and use."""

    def __init__(self, ports: dict[str, int], python: str, api_env: dict) -> None:
        self.ports = ports
        self.python = python
        self.api_env = api_env
        self.started = time.time()
        self.browser: str | None = None
        self.windows: list[dict] = []  # every window opened, so it can reopen one
        self.people: list[dict] = []  # who is signed in where
        self.phone: dict = {"enabled": False, "host": None, "scheme": "http", "links": []}
        self.voice_on = False
        self.insecure_windows = False
        # Started in main() once the services exist, so it can attribute usage
        # to this run's own processes rather than only reporting a total.
        self.monitor = None

    # -- the voice server, which owns the model settings -------------------- #

    def _voice(self, path: str, payload: dict | None = None) -> dict:
        """Talk to the token server on this machine. It never leaves localhost."""
        url = f"http://127.0.0.1:{self.ports['voice']}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def voice_config(self, payload: dict | None = None) -> dict:
        if not self.voice_on:
            return {"error": "The voice server is not running in this session."}
        try:
            if payload:
                return self._voice("/config", payload)
            return self._voice("/config")
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            return {"error": str(error)}

    # -- what the Live API has cost ----------------------------------------- #

    def cost(self) -> dict:
        """Price the usage the browser reported, per session and per model.

        The figures are what this usage *would* cost on the paid tier; a free
        tier key is billed nothing. Rates and their date live in pricing.json.
        """
        try:
            pricing = json.loads((CONSOLE_DIR / "pricing.json").read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return {"error": f"pricing table unreadable: {error}"}

        sessions: list[dict] = []
        if self.voice_on:
            try:
                sessions = self._voice("/usage").get("sessions", [])
            except (urllib.error.URLError, TimeoutError, ValueError):
                sessions = []

        per_million = pricing.get("per_tokens", 1_000_000)
        priced, by_model, totals = [], {}, {"tokens": 0, "cost": 0.0}

        for session in sessions:
            model = session.get("model", "")
            rates = pricing["models"].get(model, pricing["fallback"])
            lines, cost = [], 0.0

            for direction, details in (
                ("input", session.get("promptDetails") or []),
                ("output", session.get("responseDetails") or []),
            ):
                for detail in details:
                    modality = str(detail.get("modality", "TEXT")).upper()
                    tokens = int(detail.get("tokenCount") or 0)
                    rate = rates[direction].get(modality, rates[direction].get("TEXT", 0))
                    amount = tokens / per_million * rate
                    cost += amount
                    lines.append(
                        {
                            "direction": direction,
                            "modality": modality,
                            "tokens": tokens,
                            "rate": rate,
                            "cost": round(amount, 6),
                        }
                    )

            tokens_total = int(session.get("totalTokenCount") or 0)
            priced.append(
                {
                    "sessionId": session.get("sessionId", "")[:8],
                    "model": model,
                    "label": rates.get("label", model),
                    "tokens": tokens_total,
                    "cost": round(cost, 6),
                    "lines": lines,
                    "at": session.get("at", ""),
                }
            )
            bucket = by_model.setdefault(
                model, {"label": rates.get("label", model), "tokens": 0, "cost": 0.0}
            )
            bucket["tokens"] += tokens_total
            bucket["cost"] = round(bucket["cost"] + cost, 6)
            totals["tokens"] += tokens_total
            totals["cost"] = round(totals["cost"] + cost, 6)

        return {
            "sessions": sorted(priced, key=lambda row: row["at"], reverse=True),
            "byModel": [{"model": key, **value} for key, value in by_model.items()],
            "totals": totals,
            "checked": pricing.get("_checked"),
            "source": pricing.get("_source"),
            "voiceRunning": self.voice_on,
        }

    # -- state -------------------------------------------------------------- #

    def state(self) -> dict:
        services = []
        for tag, label in (
            ("api", "Gamira API"),
            ("worker", "Background worker"),
            ("parent", "Parent App server"),
            ("dash", "Dashboard server"),
            ("watch", "Watch simulator"),
            ("voice", "Voice lab (local only)"),
        ):
            if tag not in SPECS:
                continue
            process = SPECS[tag].get("process")
            services.append(
                {
                    "tag": tag,
                    "label": label,
                    "running": running(tag),
                    "pid": process.pid if process else None,
                    "port": {
                        "api": self.ports["api"],
                        "parent": self.ports["parent"],
                        "dash": self.ports["dash"],
                        "watch": self.ports["watch"],
                        "voice": self.ports["voice"],
                    }.get(tag),
                }
            )
        database = sqlite_file()
        return {
            "services": services,
            "windows": self.windows,
            "people": self.people,
            "ports": self.ports,
            "phone": self.phone,
            "uptime": int(time.time() - self.started),
            "database": {
                "path": str(database) if database else None,
                "kind": "sqlite" if database else "postgresql",
                "size": database.stat().st_size if database and database.is_file() else 0,
            },
        }

    def health(self) -> dict:
        """What the machine looks like right now.

        Kept separate from ``state()`` because the console polls state
        constantly for logs and service cards, and sampling the machine on that
        cadence would make the monitor part of the problem it exists to catch.
        """
        if self.monitor is None:
            return {
                "available": False,
                "reason": "The system monitor could not start on this machine.",
            }
        snapshot = self.monitor.snapshot()
        # Name the processes, so "3.1 GB" reads as "the two Vite servers".
        labels = {}
        for tag, spec in SPECS.items():
            process = spec.get("process")
            if process is not None:
                labels[process.pid] = tag
        for row in snapshot.get("own_processes", []):
            row["tag"] = labels.get(row["pid"], "?")
        return snapshot

    def track_processes(self) -> None:
        """Point the monitor at whatever this run currently owns."""
        if self.monitor is None:
            return
        pids = [
            spec["process"].pid
            for spec in SPECS.values()
            if spec.get("process") is not None
        ]
        self.monitor.track(pids)

    # -- actions ------------------------------------------------------------ #

    def act(self, name: str, payload: dict) -> dict:
        handler = {
            "restart": self._restart,
            "reset-db": self._reset_db,
            "seed": self._seed,
            "clear-logs": self._clear_logs,
            "open-window": self._open_window,
            "open-docs": self._open_docs,
            "test-sos": self._test_sos,
            "test-flag": self._test_flag,
            "stop-all": self._stop_all,
        }.get(name)
        if handler is None:
            return {"ok": False, "message": f"unknown action: {name}"}
        try:
            return {"ok": True, "message": handler(payload)}
        except Exception as error:  # a broken button must not take the run down
            fail(f"console action '{name}' failed: {error}")
            return {"ok": False, "message": str(error)}

    def _restart(self, payload: dict) -> str:
        return restart(str(payload.get("service", "")))

    def _reset_db(self, payload: dict) -> str:
        # The API holds the SQLite file open, and dropping tables underneath it
        # is how a demo ends up with half a schema. Stop, rebuild, start.
        say("rebuilding the database…", "db")
        api_was_running = running("api")
        if api_was_running:
            process = SPECS["api"].get("process")
            if process:
                kill(process)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
        result = self._run_seed(reset=True)
        if api_was_running:
            restart("api")
        return result

    def _seed(self, payload: dict) -> str:
        return self._run_seed(reset=False)

    def _run_seed(self, reset: bool) -> str:
        command = [self.python, "-m", "app.db.seed"] + (["--reset"] if reset else [])
        finished = subprocess.run(
            command,
            cwd=BACKEND,
            env={**os.environ, **self.api_env},
            capture_output=True,
            text=True,
        )
        for line in (finished.stdout or "").splitlines():
            say(line, "db")
        if finished.returncode != 0:
            raise RuntimeError(finished.stderr.strip().splitlines()[-1:] or "seed failed")
        return "database rebuilt" if reset else "seed checked"

    def _open_window(self, payload: dict) -> str:
        index = int(payload.get("index", -1))
        if not 0 <= index < len(self.windows):
            raise ValueError("no such window")
        window = self.windows[index]
        open_window(
            self.browser,
            window["url"],
            window["name"],
            tuple(window["size"]),
            tuple(window["slot"]),
            insecure=self.insecure_windows,
        )
        return f"opened {window['label']}"

    def _open_docs(self, payload: dict) -> str:
        url = f"http://127.0.0.1:{self.ports['api']}/docs"
        open_window(self.browser, url, "api-docs", (900, 900), (60, 40))
        return "opened the API documentation"

    def _as_person(self, subject: str, path: str, payload: dict) -> dict:
        """POST to the API as a seeded identity, from this process.

        Server-side, so the console never needs a CORS hole in the API and the
        request goes through exactly the authorisation a real client hits.
        """
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.ports['api']}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer dev:{subject}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _test_sos(self, payload: dict) -> str:
        """Raise an SOS the way the Parent App would, for testing the dashboard."""
        subject = str(payload.get("subject") or "")
        senior_id = str(payload.get("senior_id") or "")
        if not subject or not senior_id:
            raise ValueError("which person?")
        answer = self._as_person(
            subject,
            f"/api/v1/seniors/{senior_id}/sos",
            {"source": "parent_app", "note": None},
        )
        told = len(answer["notified_user_ids"])
        return f"SOS raised for {answer['senior_name']} — {told} alerted"

    def _test_flag(self, payload: dict) -> str:
        """Raise the notice a watch raises, without waiting for the watch."""
        subject = str(payload.get("subject") or "")
        senior_id = str(payload.get("senior_id") or "")
        if not subject or not senior_id:
            raise ValueError("which person?")
        answer = self._as_person(
            subject,
            f"/api/v1/seniors/{senior_id}/device-flags",
            {
                "metric": "heart_rate",
                "value": 138,
                "unit": "bpm",
                "reason": "Above the upper limit of 110 bpm set on the watch.",
                "source_device": "Gamira Watch (console test)",
                "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        told = len(answer["notified_user_ids"])
        return f"flagged a reading for {answer['senior_name']} — {told} told"

    def _clear_logs(self, payload: dict) -> str:
        LOGS.clear()
        REQUESTS.clear()
        return "logs cleared"

    def _stop_all(self, payload: dict) -> str:
        threading.Thread(target=stop_all, daemon=True).start()
        return "stopping everything"

    # -- database ----------------------------------------------------------- #

    def tables(self) -> list[dict]:
        with read_only_db() as connection:
            names = [
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            return [
                {
                    "name": name,
                    "rows": connection.execute(
                        f'SELECT COUNT(*) AS n FROM "{name}"'  # noqa: S608 - name from sqlite_master
                    ).fetchone()["n"],
                }
                for name in names
            ]

    def rows(self, table: str, limit: int, offset: int) -> dict:
        with read_only_db() as connection:
            known = {row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if table not in known:
                raise ValueError("no such table")
            cursor = connection.execute(
                f'SELECT * FROM "{table}" LIMIT ? OFFSET ?',  # noqa: S608 - checked above
                (min(limit, 200), offset),
            )
            found = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return {
                "columns": columns,
                "rows": [[_cell(row[column]) for column in columns] for row in found],
            }

    def query(self, sql: str) -> dict:
        if not SAFE_QUERY.match(sql or ""):
            raise ValueError("Only SELECT statements are allowed here.")
        if ";" in sql.strip().rstrip(";"):
            raise ValueError("One statement at a time.")
        with read_only_db() as connection:
            cursor = connection.execute(sql.strip().rstrip(";"))
            found = cursor.fetchmany(200)
            columns = [description[0] for description in cursor.description]
            return {
                "columns": columns,
                "rows": [[_cell(value) for value in row] for row in found],
            }


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= 160 else text[:157] + "…"


def console_handler(console: Console):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            """The console polls every second; its own log would drown the run's."""

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _query(self) -> dict[str, str]:
            _, _, raw = self.path.partition("?")
            pairs = [part.split("=", 1) for part in raw.split("&") if "=" in part]
            return {key: urllib.parse.unquote_plus(value) for key, value in pairs}

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?")[0]
            try:
                if path in ("/", "/index.html"):
                    page = (CONSOLE_DIR / "console.html").read_bytes()
                    self._send(200, page, "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._json(200, console.state())
                elif path == "/api/logs":
                    after = int(self._query().get("after", "0") or 0)
                    self._json(200, {"seq": LOGS.seq, "entries": LOGS.after(after)})
                elif path == "/api/requests":
                    self._json(
                        200,
                        {
                            "recent": REQUESTS.recent(),
                            "endpoints": REQUESTS.stats(),
                            "total": REQUESTS.seq,
                        },
                    )
                elif path == "/api/health":
                    console.track_processes()
                    self._json(200, console.health())
                elif path == "/api/voice":
                    self._json(200, console.voice_config())
                elif path == "/api/cost":
                    self._json(200, console.cost())
                elif path == "/api/db/tables":
                    self._json(200, {"tables": console.tables()})
                elif path == "/api/db/rows":
                    params = self._query()
                    self._json(
                        200,
                        console.rows(
                            params.get("table", ""),
                            int(params.get("limit", "50") or 50),
                            int(params.get("offset", "0") or 0),
                        ),
                    )
                else:
                    self._json(404, {"error": "not found"})
            except Exception as error:
                self._json(400, {"error": str(error)})

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            path = self.path.split("?")[0]
            try:
                if path == "/api/action":
                    self._json(200, console.act(payload.get("name", ""), payload))
                elif path == "/api/voice":
                    self._json(200, console.voice_config(payload))
                elif path == "/api/db/query":
                    self._json(200, console.query(payload.get("sql", "")))
                else:
                    self._json(404, {"error": "not found"})
            except Exception as error:
                self._json(400, {"error": str(error)})

    return Handler


def start_console(console: Console, host: str = "127.0.0.1") -> bool:
    try:
        server = ThreadingHTTPServer(
            (host, console.ports["console"]), console_handler(console)
        )
    except OSError as error:
        fail(f"could not start the server console: {error}")
        return False
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return True


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #


def load_dotenv(path: Path) -> dict[str, str]:
    """Read a .env file without adding a dependency. Real env vars still win."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip("'\"")
    return values


def backend_python() -> str:
    candidate = BACKEND / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python")
    if candidate.is_file():
        return str(candidate)
    fail(f"No virtual environment at {candidate}. Falling back to {sys.executable}.")
    say("  create one with:  cd gamira-backend && python -m venv .venv && "
        ".venv\\Scripts\\pip install -r requirements-dev.txt")
    return sys.executable


def ensure_node_modules(npm: str, project: Path) -> bool:
    if (project / "node_modules").is_dir():
        return True
    say(f"installing dependencies for {project.name} (one time)…")
    return subprocess.run([npm, "install"], cwd=project).returncode == 0


def ensure_voice_dependency(python: str) -> bool:
    """The token server needs google-genai; pyaudio is only for the CLI client."""
    probe = subprocess.run(
        [python, "-c", "import google.genai"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        return True
    say("installing google-genai for the voice token server (one time)…", "voice")
    installed = subprocess.run(
        [python, "-m", "pip", "install", "--quiet", "google-genai>=1.68.0"]
    )
    return installed.returncode == 0


def resolve_people(api_port: int, wanted: list[tuple[str, str, str]]) -> list[dict]:
    """Look up who each window will be, and warn when an account is empty.

    The usual cause of an empty one is a database seeded before a person was
    added to `app/db/seed.py`, which shows up as a blank app rather than an
    error. The senior id resolved here is also what the console's test SOS
    uses, so the page never has to call the API across origins.
    """
    people: list[dict] = []
    for subject, label, role in wanted:
        body: dict = {}
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{api_port}/api/v1/me",
                headers={"Authorization": f"Bearer dev:{subject}"},
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            fail(f"could not check dev:{subject} ({error})")

        user_id = (body.get("user") or {}).get("id")
        seniors = body.get("seniors") or []
        # Only a Parent App or a watch *is* someone. A dashboard belongs to a
        # family member who looks after several people, so it claims none.
        own = None
        if role in ("parent", "watch"):
            own = next((s for s in seniors if s.get("user_id") == user_id), None) or (
                seniors[0] if seniors else None
            )
        missing = own is None if role in ("parent", "watch") else not body.get("families")
        if missing:
            fail(f"dev:{subject} ({label}) has no care record yet.")
            say("  rebuild the sample data:  python run.py --reset-db")

        people.append(
            {
                "subject": subject,
                "label": label,
                "role": role,
                "senior_id": own["id"] if own else None,
                "person": own["preferred_name"] if own else "",
            }
        )
    return people


def bootstrap_database(python: str, env: dict, reset: bool) -> bool:
    say("applying migrations…", "db")
    migrate = subprocess.run(
        [python, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    if migrate.returncode != 0:
        fail("alembic upgrade failed:")
        print(migrate.stdout or migrate.stderr)
        return False

    command = [python, "-m", "app.db.seed"] + (["--reset"] if reset else [])
    seeded = subprocess.run(
        command,
        cwd=BACKEND,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    for line in (seeded.stdout or "").splitlines():
        say(line, "db")
    if seeded.returncode != 0:
        fail("seeding failed:")
        print(seeded.stderr)
        return False
    return True


# --------------------------------------------------------------------------- #
# Start-up summary
# --------------------------------------------------------------------------- #


def summary(
    parents,
    dashboards,
    watches,
    voice_on: bool,
    console_on: bool,
    ports: dict[str, int],
    phone: dict,
) -> None:
    rule = "─" * 66
    print(f"\n{COLORS['run']}{rule}")
    print(f"  Gamira is running{RESET}")
    print(f"{COLORS['run']}{rule}{RESET}")

    app = phone.get("scheme", "http")
    rows = [
        ("API", f"http://127.0.0.1:{ports['api']}/docs", "FastAPI · SQLite · dev auth"),
        ("Worker", "python -m app.worker", "doses, reminders, delivery, escalation"),
    ]
    for index, (subject, label) in enumerate(parents):
        rows.append(
            (
                f"Parent App {index + 1}",
                f"{app}://localhost:{ports['parent']}/?dev={subject}",
                label,
            )
        )
    for index, (subject, label) in enumerate(dashboards):
        rows.append(
            (
                f"Dashboard {index + 1}",
                f"{app}://localhost:{ports['dash']}/?dev={subject}",
                label,
            )
        )
    for index, (_, label) in enumerate(watches):
        rows.append(
            (f"Watch {index + 1}", f"http://localhost:{ports['watch']}/?w={index}", label)
        )
    if voice_on:
        rows.append(
            (
                "Voice lab",
                f"http://localhost:{ports['voice']}/token",
                "console model picker · the apps use /api/v1/ai/live-sessions",
            )
        )
    if console_on:
        rows.append(
            (
                "Console",
                f"http://localhost:{ports['console']}/",
                "logs, controls, database",
            )
        )

    if phone.get("enabled"):
        rows.append(
            (
                "On your phone",
                f"{app}://{phone['host']}:{ports['parent']}/",
                "QR codes in the console",
            )
        )

    for name, url, who in rows:
        print(f"  {BOLD}{name:<14}{RESET}{url:<46}{DIM}{who}{RESET}")

    print(f"\n  {BOLD}Try this{RESET}")
    print("  1. In a watch window pick \"Racing heart\" — the value appears on that")
    print("     person's Health screen and in the dashboard within a few seconds.")
    print("  2. Press SOS in a Parent App — the dashboard raises a red alert, and")
    print("     the line below shows the API recording it.")
    print("  3. Confirm a dose in the Parent App — the dashboard timeline updates.")
    if console_on:
        print("  4. The console window has the logs with filters, request timings,")
        print("     the voice lab, what it has cost, and the database.")
    if not phone.get("enabled"):
        print(f"  {DIM}Run with --phone to open the apps on a phone, mic and all.{RESET}")
    print(f"\n  {DIM}Ctrl+C stops everything.{RESET}")
    print(f"{COLORS['run']}{rule}{RESET}\n")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the Gamira backend, both apps and the watch simulator."
    )
    parser.add_argument("--parents", type=int, default=COUNTS["parents"])
    parser.add_argument("--dashboards", type=int, default=COUNTS["dashboards"])
    parser.add_argument("--watches", type=int, default=COUNTS["watches"])
    parser.add_argument("--api-port", type=int, default=API_PORT)
    # Handy when another dev server already holds a port: move the whole stack
    # rather than stopping whatever is running.
    parser.add_argument("--parent-port", type=int, default=PARENT_PORT)
    parser.add_argument("--dashboard-port", type=int, default=DASHBOARD_PORT)
    parser.add_argument("--watch-port", type=int, default=WATCH_PORT)
    parser.add_argument("--voice-port", type=int, default=VOICE_PORT)
    parser.add_argument("--console-port", type=int, default=CONSOLE_PORT)
    parser.add_argument(
        "--reset-db", action="store_true", help="Rebuild the local database from seed."
    )
    parser.add_argument("--no-voice", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="start even when the machine is short of memory or disk",
    )
    parser.add_argument(
        "--keep-orphans",
        action="store_true",
        help="do not stop leftover Gamira processes from an earlier run",
    )
    parser.add_argument("--no-console", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--phone",
        "--lan",
        dest="phone",
        action="store_true",
        help=(
            "Serve the apps to your local network over https, so they can be "
            "opened on a phone with a working microphone. The console tab "
            "shows the addresses and QR codes."
        ),
    )
    parser.add_argument(
        "--raw-logs", action="store_true", help="Print the API's log lines unformatted."
    )
    parser.add_argument(
        "--clean-profiles",
        action="store_true",
        help="Throw away the browser profiles first (signs every window out).",
    )
    return parser.parse_args()


def main() -> int:
    global KILL_JOB
    KILL_JOB = open_kill_job()

    args = parse_args()
    ports = {
        "api": args.api_port,
        "parent": args.parent_port,
        "dash": args.dashboard_port,
        "watch": args.watch_port,
        "voice": args.voice_port,
        "console": args.console_port,
    }
    api_port = ports["api"]

    # Before anything is started: clear leftovers from an earlier run, and
    # refuse a machine that is already out of room. Both exist because of the
    # 17 Aug 2026 crash — several unsupervised workers polling one SQLite file
    # on a machine with 7% disk free, which nothing was watching.
    if not args.keep_orphans:
        reap_orphans()
    if not check_machine_headroom() and not args.force:
        say("nothing was started. Use --force to override.")
        return 1

    parents = PARENTS[: max(0, args.parents)]
    dashboards = DASHBOARDS[: max(0, args.dashboards)]
    watches = WATCHES[: max(0, args.watches)]
    for name, wanted, roster in (
        ("parents", args.parents, PARENTS),
        ("dashboards", args.dashboards, DASHBOARDS),
        ("watches", args.watches, WATCHES),
    ):
        if wanted > len(roster):
            fail(f"only {len(roster)} {name} are configured; add a row to run.py.")

    npm = shutil.which("npm.cmd" if IS_WINDOWS else "npm")
    if not npm:
        fail("npm is not on PATH.")
        return 1
    python = backend_python()

    needed = {api_port: ("API", "--api-port")}
    if parents:
        needed[ports["parent"]] = ("Parent App", "--parent-port")
    if dashboards:
        needed[ports["dash"]] = ("Family Dashboard", "--dashboard-port")
    if watches:
        needed[ports["watch"]] = ("watch simulator", "--watch-port")
    console_on = CONSOLE and not args.no_console
    if console_on:
        needed[ports["console"]] = ("server console", "--console-port")
    for port, (what, flag) in needed.items():
        if port_in_use(port):
            fail(f"port {port} is already in use ({what}).")
            say(f"  stop whatever is holding it, or move this one: {flag} {port + 100}")
            return 1

    if parents and not ensure_node_modules(npm, PARENT_APP):
        return 1
    if dashboards and not ensure_node_modules(npm, DASHBOARD):
        return 1

    # Voice: the key lives in the Parent App's .env, is passed to the API so it
    # can mint Live tokens, and never reaches a browser. The standalone token
    # server below stays only as the console's voice lab.
    voice_on = VOICE and not args.no_voice and bool(parents)
    if voice_on:
        gemini_key = os.environ.get("GEMINI_API_KEY") or load_dotenv(
            PARENT_APP / ".env"
        ).get("GEMINI_API_KEY", "")
        if not gemini_key:
            fail("GEMINI_API_KEY is not set — starting without voice.")
            say("  put it in gamira-parent-app-original/.env to enable the mic.")
            voice_on = False
        elif port_in_use(ports["voice"]):
            fail(f"port {ports['voice']} is busy — starting without voice.")
            voice_on = False
        elif not ensure_voice_dependency(python):
            fail("could not install google-genai — starting without voice.")
            voice_on = False
        else:
            os.environ["GEMINI_API_KEY"] = gemini_key

    if args.clean_profiles and PROFILES.exists():
        shutil.rmtree(PROFILES, ignore_errors=True)

    # Phone testing: the apps go on the network over https, because a browser
    # gives a page the microphone only on a secure origin. The token server and
    # the API stay on localhost — the phone reaches them through the dev
    # server's proxy, so the Gemini key is never on the network.
    phone_host, tls = None, None
    if args.phone:
        phone_host = lan_address()
        if phone_host is None:
            fail("could not work out this machine's network address — phone tab off.")
        else:
            tls = make_certificate(python, phone_host)
            if tls is None:
                phone_host = None
    scheme = "https" if tls else "http"

    # The API's own settings. Passed as environment rather than written to
    # .env, so nothing on disk changes. DEBUG is set explicitly because a
    # machine-level DEBUG value that is not a boolean stops settings loading.
    api_env = {
        "APP_ENV": "local",
        "API_PORT": str(api_port),
        "DEBUG": "false",
        "AUTH_MODE": "dev",
        "LOG_FORMAT": "console",
        "LOG_LEVEL": "INFO",
        # Push is not configured locally. "fake" records the attempt and its
        # outcome without pretending anything reached a phone.
        "FCM_PROVIDER": "fake",
        # With a key present the backend mints real Live tokens itself, at
        # POST /api/v1/ai/live-sessions. Without one it uses the deterministic
        # fake provider, and every non-AI path still works.
        "AI_PROVIDER": "gemini" if voice_on else "fake",
    }
    if voice_on:
        api_env["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

    if not bootstrap_database(python, api_env, args.reset_db):
        return 1

    say(f"starting the API on port {api_port}…")
    api_command = [
        python, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(api_port),
    ]
    if API_RELOAD:
        api_command.append("--reload")
    spawn(
        "api",
        api_command,
        BACKEND,
        api_env,
        render=None if args.raw_logs else render_api,
    )
    if not wait_for_port(api_port, "the API"):
        stop_all()
        return 1

    # The worker. Dose events, late/missed transitions, reminders, push delivery
    # and SOS escalation all happen here, not in the API — so the medication
    # loop keeps working with no screen open. Without it, GET /doses returns an
    # empty day, because the reads no longer generate anything.
    say("starting the background worker…")
    spawn(
        "worker",
        [python, "-m", "app.worker"],
        BACKEND,
        {**api_env, "WORKER_RUN_SCHEDULER": "true"},
        render=None if args.raw_logs else render_api,
    )

    people = resolve_people(
        api_port,
        [(subject, label, "parent") for subject, label in parents]
        + [(subject, label, "dash") for subject, label in dashboards]
        + [(subject, label, "watch") for subject, label in watches],
    )

    front_env = {
        "GAMIRA_API_TARGET": f"http://127.0.0.1:{api_port}",
        "GAMIRA_TOKEN_TARGET": f"http://127.0.0.1:{ports['voice']}",
        "VITE_POLL_MS": str(POLL_MS),
        "BROWSER": "none",  # Vite must not open a window of its own
    }
    if tls:
        front_env["GAMIRA_TLS_CERT"], front_env["GAMIRA_TLS_KEY"] = tls

    def vite(port: int) -> list[str]:
        command = [npm, "run", "dev", "--", "--port", str(port), "--strictPort"]
        if phone_host:
            command.append("--host")  # bind every interface, not just localhost
        return command

    if parents:
        spawn("parent", vite(ports["parent"]), PARENT_APP, front_env)
    if dashboards:
        spawn("dash", vite(ports["dash"]), DASHBOARD, front_env)

    if voice_on:
        # The browser reaches /gemini-token through the dev server, so these
        # origins are only about a direct call during hand testing.
        origins = [f"http://localhost:{ports['parent']}"]
        if phone_host:
            origins += [
                f"{scheme}://localhost:{ports['parent']}",
                f"{scheme}://{phone_host}:{ports['parent']}",
            ]
        spawn(
            "voice",
            [python, "-u", "gemini_token_server.py"],
            PARENT_APP,
            {
                "GEMINI_TOKEN_PORT": str(ports["voice"]),
                "GEMINI_TOKEN_ALLOW_ORIGIN": ",".join(dict.fromkeys(origins)),
            },
        )

    if watches:
        pairs = []
        for subject, label in watches:
            pairs += ["--pair", f"{subject}={label}"]
        spawn(
            "watch",
            [
                sys.executable if python == sys.executable else python,
                "-u",
                str(WATCH_SIM / "sim_server.py"),
                "--api", f"http://127.0.0.1:{api_port}",
                "--port", str(ports["watch"]),
                "--host", "0.0.0.0" if phone_host else "127.0.0.1",
                "--interval", str(WATCH_INTERVAL_SECONDS),
                *pairs,
            ],
            WATCH_SIM,
        )

    ready = True
    if parents:
        ready &= wait_for_port(ports["parent"], "the Parent App dev server")
    if dashboards:
        ready &= wait_for_port(ports["dash"], "the Family Dashboard dev server")
    if watches:
        ready &= wait_for_port(ports["watch"], "the watch simulator")
    if not ready:
        stop_all()
        return 1

    console = Console(ports, python, api_env)
    console.people = people
    console.voice_on = voice_on
    if SystemMonitor is not None:
        # Watches the machine for the rest of the run. A stall like the one on
        # 17 Aug 2026 — a hard crash under sustained test load, then a
        # firmware-throttled CPU — showed up nowhere in this console before.
        console.monitor = SystemMonitor(interval_seconds=3.0)
        console.monitor.start()
        console.track_processes()
    if console_on:
        console_on = start_console(console, "0.0.0.0" if phone_host else "127.0.0.1")

    # Every window this run knows how to open, so the console can put one back
    # after it has been closed without restarting the whole stack.
    tiler = Tiler()
    planned: list[dict] = []
    for subject, label in parents:
        planned.append(
            {
                "label": f"Parent App · {label}",
                "name": f"parent-{subject}",
                "url": f"{scheme}://localhost:{ports['parent']}/?dev={subject}",
                "lan": (
                    f"{scheme}://{phone_host}:{ports['parent']}/?dev={subject}"
                    if phone_host
                    else None
                ),
                "size": list(PHONE_SIZE),
                "slot": list(tiler.place(PHONE_SIZE)),
            }
        )
    for subject, label in dashboards:
        planned.append(
            {
                "label": f"Dashboard · {label}",
                "name": f"dash-{subject}",
                "url": f"{scheme}://localhost:{ports['dash']}/?dev={subject}",
                "lan": (
                    f"{scheme}://{phone_host}:{ports['dash']}/?dev={subject}"
                    if phone_host
                    else None
                ),
                "size": list(PHONE_SIZE),
                "slot": list(tiler.place(PHONE_SIZE)),
            }
        )
    for index, (_, label) in enumerate(watches):
        planned.append(
            {
                "label": f"Watch · {label}",
                "name": f"watch-{index}",
                # The watch face is served by Python, not Vite, so it stays on
                # http even when the apps are on https.
                "url": f"http://localhost:{ports['watch']}/?w={index}",
                "lan": (
                    f"http://{phone_host}:{ports['watch']}/?w={index}"
                    if phone_host
                    else None
                ),
                "size": list(WATCH_SIZE),
                "slot": list(tiler.place(WATCH_SIZE)),
            }
        )
    if console_on:
        slot, size = tiler.place_wide(CONSOLE_SIZE)
        planned.append(
            {
                "label": "Server console",
                "name": "console",
                "url": f"http://localhost:{ports['console']}/",
                "lan": f"http://{phone_host}:{ports['console']}/" if phone_host else None,
                "size": list(size),
                "slot": list(slot),
            }
        )
    console.windows = planned

    if phone_host:
        links = [window for window in planned if window.get("lan")]
        codes = make_qr_codes(python, [window["lan"] for window in links])
        console.phone = {
            "enabled": True,
            "host": phone_host,
            "scheme": scheme,
            "secure": bool(tls),
            "links": [
                {"label": window["label"], "url": window["lan"], "qr": codes.get(window["lan"], "")}
                for window in links
            ],
        }
        say(f"phone testing on: {scheme}://{phone_host}:{ports['parent']}")
        say("  the apps are reachable on your network; the certificate is self-signed.")

    if OPEN_WINDOWS and not args.no_browser:
        browser = find_browser()
        if browser is None:
            fail("no Chrome or Edge found — opening in the default browser.")
            say("  the windows will not be phone-sized.")
        console.browser = browser
        console.insecure_windows = bool(tls)
        for window in planned:
            open_window(
                browser,
                window["url"],
                window["name"],
                tuple(window["size"]),
                tuple(window["slot"]),
                insecure=bool(tls),
            )

    summary(parents, dashboards, watches, voice_on, console_on, ports, console.phone)

    try:
        while not shutting_down.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        print()
        say("shutting down")
        stop_all()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        stop_all()
        sys.exit(0)
