"""The worker process.

    python -m app.worker

Same codebase, same models, same services as the API — a different entry point,
not a different application. It answers no real request; if it stops, the API
keeps serving reads and writes, and the work it was doing is picked up by the
next worker when its leases expire.

It does bind a bare TCP listener on $PORT when one is set (Cloud Run always
sets one). Cloud Run Services require every container to accept connections
on that port to be considered healthy, worker or not — this holds the socket
open and does nothing else with it, which is enough for a TCP-only probe and
costs nothing at rest. Skipped entirely when $PORT is unset (plain local runs,
--once), so nothing changes for those.

Options:
    --once            run every ready job, then exit (useful in CI and cron)
    --worker-id NAME  override the generated host-pid identifier
    --no-scheduler    do not enqueue recurring ticks (Cloud Scheduler drives them)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_sessionmaker
from app.jobs.runner import Worker

logger = get_logger("app.worker")


async def _handle_probe_connection(
    _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    # A TCP probe only needs the connection to open; nothing here has to read
    # or write anything for that to succeed.
    with contextlib.suppress(OSError):
        writer.close()


async def _serve_health_probe() -> asyncio.AbstractServer | None:
    port = os.environ.get("PORT")
    if not port:
        return None
    server = await asyncio.start_server(_handle_probe_connection, "0.0.0.0", int(port))
    logger.info("worker_health_probe_listening", extra={"port": port})
    return server


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--no-scheduler", action="store_true")
    return parser.parse_args(argv)


def _install_signal_handlers(worker: Worker) -> None:
    """Ask the worker to finish what it holds, rather than killing it.

    Windows has no SIGTERM through asyncio's loop, and a signal handler cannot
    be installed on a non-main thread, so both cases fall back to the default
    behaviour rather than failing to start.
    """
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, worker.request_stop)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.no_scheduler:
        settings = settings.model_copy(update={"worker_run_scheduler": False})
    configure_logging(settings.log_level, settings.log_format)

    worker = Worker(
        get_sessionmaker(), settings=settings, worker_id=args.worker_id
    )
    probe_server: asyncio.AbstractServer | None = None
    try:
        if args.once:
            processed = await worker.run_once()
            logger.info("worker_run_once_complete", extra={"processed": processed})
            return 0
        probe_server = await _serve_health_probe()
        _install_signal_handlers(worker)
        await worker.run()
        return 0
    finally:
        if probe_server is not None:
            probe_server.close()
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
