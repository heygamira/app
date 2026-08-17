"""Starts the Gamira app and the voice token server together.

    python run.py

Ctrl+C stops both. If either one dies, the other is shut down too, so you
never end up with a half-running stack.
"""

import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from gemini_env import load_env

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = platform.system() == "Windows"

# Vite prints "➜" in its banner, which a cp1252 console cannot encode — and an
# unhandled UnicodeEncodeError in an output thread would take the pump down.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN_PORT = int(os.environ.get("GEMINI_TOKEN_PORT", "8787"))
VITE_PORT = int(os.environ.get("VITE_PORT", "5173"))

# ANSI is on by default in Windows Terminal and every other shell we care
# about, but not in old conhost — so it degrades to plain text there.
RESET = "\033[0m"
COLORS = {"voice": "\033[35m", "app": "\033[36m", "run": "\033[32m", "err": "\033[31m"}

processes = []
shutting_down = threading.Event()


def say(tag, message, color="run"):
    print(f"{COLORS.get(color, '')}[{tag}]{RESET} {message}", flush=True)


def port_in_use(port):
    # Check both stacks: on Windows "localhost" resolves to ::1 first, so a
    # Vite server already holding the port is invisible to an IPv4-only probe.
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.4)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def pump(process, tag, color):
    """Stream a child's output with a prefix so the two are tellable apart."""
    try:
        for line in process.stdout:
            text = line.rstrip()
            if text:
                print(f"{COLORS[color]}[{tag}]{RESET} {text}", flush=True)
    except Exception as exc:  # never let a print failure kill the pump
        say("run", f"{tag} output stopped: {exc}", "err")
    process.wait()  # otherwise returncode is still None right after EOF
    if not shutting_down.is_set():
        say("run", f"{tag} exited with code {process.returncode}", "err")
        stop_all()


def spawn(tag, color, command):
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        # Keeps Ctrl+C in this console from reaching the children directly, so
        # we can shut them down in order instead of racing them.
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    processes.append((tag, process))
    threading.Thread(target=pump, args=(process, tag, color), daemon=True).start()
    return process


def stop_all():
    if shutting_down.is_set():
        return
    shutting_down.set()
    for tag, process in processes:
        if process.poll() is not None:
            continue
        say("run", f"stopping {tag}...")
        if IS_WINDOWS:
            # npm spawns node as a grandchild; terminate() would only kill the
            # cmd shim and leave the dev server holding the port.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
            )
        else:
            process.terminate()
    for _, process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def preflight():
    load_env()

    if not os.environ.get("GEMINI_API_KEY"):
        say("run", "GEMINI_API_KEY is not set.", "err")
        say("run", "Put it in .env at the repo root:  GEMINI_API_KEY = your-key")
        return False

    npm = shutil.which("npm.cmd" if IS_WINDOWS else "npm")
    if not npm:
        say("run", "npm is not on PATH.", "err")
        return False

    for port, what in ((TOKEN_PORT, "token server"), (VITE_PORT, "dev server")):
        if port_in_use(port):
            say("run", f"port {port} is already in use ({what}).", "err")
            say("run", "Something is still running from a previous session.")
            return False

    if not (ROOT / "node_modules").is_dir():
        say("run", "node_modules missing — running npm install (one time)...")
        if subprocess.run([npm, "install"], cwd=ROOT).returncode != 0:
            say("run", "npm install failed.", "err")
            return False

    return npm


def main():
    npm = preflight()
    if not npm:
        return 1

    say("run", "starting Gamira...")
    spawn("voice", "voice", [sys.executable, "-u", "gemini_token_server.py"])

    # Give the token server a moment to bind, so its "serving ..." line lands
    # before Vite's banner rather than in the middle of it.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not port_in_use(TOKEN_PORT):
        if shutting_down.is_set():
            return 1
        time.sleep(0.2)

    spawn("app", "app", [npm, "run", "dev"])

    say("run", f"app     http://localhost:{VITE_PORT}")
    say("run", f"voice   http://localhost:{TOKEN_PORT}/token")
    say("run", "Ctrl+C to stop both")

    try:
        while not shutting_down.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        print()
        say("run", "shutting down")
        stop_all()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        stop_all()
        sys.exit(0)
