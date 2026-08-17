"""System health, sampled from Windows without installing anything.

Why this exists: on 17 Aug 2026 this machine hard-crashed at 11:51 during a long
run of the backend test suite, came back with the CPU firmware-throttled, and
was unusable for minutes. Nothing in the console would have shown it coming —
it narrated the *API*, and said nothing about the machine the API was running
on.

So this samples the four things that actually precede that kind of stall, and
the console shows them with thresholds:

- CPU load, and whether firmware is *limiting* the CPU (the throttle signal)
- memory pressure and commit charge
- free space on the drive Windows pages and writes temp files to
- how much the run's own processes are using, separately from everything else

Deliberately dependency-free. `psutil` would be nicer, but a monitor that has
to be installed before it can warn you is a monitor that is not running when
you need it. Everything here comes from `ctypes` against kernel32 or from a
cached `wmic`/PowerShell call, and every reading degrades to ``None`` rather
than raising: a broken monitor must never be the thing that stops the stack.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field

IS_WINDOWS = sys.platform == "win32"

# Thresholds. Chosen from what this machine actually looked like when it fell
# over, not from round numbers.
CPU_WARN = 85.0          # sustained, per cent
CPU_CRITICAL = 95.0
MEMORY_WARN = 85.0
MEMORY_CRITICAL = 93.0
DISK_WARN_GB = 20.0      # free space on the system drive
DISK_CRITICAL_GB = 10.0
# Absolute GB is not the whole story: Windows also slows down when a large drive
# is nearly full, because defragmentation, Search indexing and shadow copies all
# need room to work. This machine sat at 7 per cent free while feeling sluggish.
DISK_WARN_PERCENT = 12.0
DISK_CRITICAL_PERCENT = 7.0
# How long a sustained level has to hold before it is worth saying anything.
# A build spiking to 100 per cent for two seconds is not a problem.
SUSTAIN_SECONDS = 20.0


# --------------------------------------------------------------------------- #
# Windows structures
# --------------------------------------------------------------------------- #


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _filetime_to_int(value: FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


@dataclass
class Sample:
    """One reading, with everything the console needs to colour it."""

    at: float
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_gb: float | None = None
    memory_total_gb: float | None = None
    commit_used_gb: float | None = None
    commit_total_gb: float | None = None
    disk_free_gb: float | None = None
    disk_total_gb: float | None = None
    disk_path: str = ""
    process_count: int | None = None
    own_cpu_percent: float | None = None
    own_memory_mb: float | None = None
    own_processes: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    throttled: bool = False
    throttle_note: str = ""


class SystemMonitor:
    """Samples the machine on a background thread and keeps a short history.

    One thread, one sample every few seconds, and a bounded history. The whole
    point is to notice a slow slide into a stall, so a monitor that itself costs
    measurable CPU would be self-defeating.
    """

    def __init__(
        self,
        *,
        interval_seconds: float = 3.0,
        history: int = 120,
        own_pids: list[int] | None = None,
    ) -> None:
        self.interval = interval_seconds
        self.history_size = history
        self.samples: list[Sample] = []
        self._own_pids = own_pids or []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Previous CPU tick totals, for the delta the percentage comes from.
        self._prev_idle = 0
        self._prev_total = 0
        self._prev_own: dict[int, tuple[float, float]] = {}
        # `wmic`/PowerShell is far too slow to call every sample, so the
        # throttle check runs on its own much slower cadence.
        self._throttle_checked_at = 0.0
        self._throttle_state = (False, "")

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="sysmon", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def track(self, pids: list[int]) -> None:
        """Tell the monitor which processes belong to this run."""
        with self._lock:
            self._own_pids = list(pids)

    def _run(self) -> None:
        # Prime the CPU delta so the first real sample is not nonsense.
        self._cpu_percent()
        while not self._stop.wait(self.interval):
            try:
                sample = self.sample()
            except Exception:
                # A monitor must never be the reason the stack stops. A failed
                # sample is skipped; the next one usually works.
                continue
            with self._lock:
                self.samples.append(sample)
                if len(self.samples) > self.history_size:
                    del self.samples[: -self.history_size]

    # -- readings ----------------------------------------------------------- #

    def _cpu_percent(self) -> float | None:
        """Whole-machine CPU, from the delta between two idle/total readings."""
        if not IS_WINDOWS:
            return None
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        idle_ticks = _filetime_to_int(idle)
        # Kernel time already includes idle time, so total is kernel + user.
        total_ticks = _filetime_to_int(kernel) + _filetime_to_int(user)

        idle_delta = idle_ticks - self._prev_idle
        total_delta = total_ticks - self._prev_total
        self._prev_idle, self._prev_total = idle_ticks, total_ticks
        if total_delta <= 0:
            return None
        return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)

    def _memory(self) -> tuple[float | None, ...]:
        if not IS_WINDOWS:
            return (None, None, None, None, None)
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return (None, None, None, None, None)
        gb = 1024**3
        total = status.ullTotalPhys / gb
        used = (status.ullTotalPhys - status.ullAvailPhys) / gb
        commit_total = status.ullTotalPageFile / gb
        commit_used = (status.ullTotalPageFile - status.ullAvailPageFile) / gb
        return (
            float(status.dwMemoryLoad),
            round(used, 1),
            round(total, 1),
            round(commit_used, 1),
            round(commit_total, 1),
        )

    def _disk(self) -> tuple[float | None, float | None, str]:
        """Free space where Windows pages and writes temp files.

        The system drive, not the project drive: a full C: is what makes the
        whole machine slow, and the project can be anywhere.
        """
        path = os.environ.get("SystemDrive", "C:") + "\\"
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            return (None, None, path)
        gb = 1024**3
        return (round(usage.free / gb, 1), round(usage.total / gb, 1), path)

    def _own_usage(self, now: float) -> tuple[float, float, list[dict]]:
        """CPU and memory for this run's own processes only.

        Separating them is the useful part: "the machine is at 95 per cent" and
        "*we* are at 95 per cent" call for different reactions.
        """
        with self._lock:
            pids = list(self._own_pids)
        if not IS_WINDOWS or not pids:
            return (0.0, 0.0, [])

        kernel32 = ctypes.windll.kernel32
        cores = os.cpu_count() or 1
        total_cpu = 0.0
        total_mb = 0.0
        rows: list[dict] = []

        for pid in pids:
            handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                self._prev_own.pop(pid, None)
                continue
            try:
                creation, exit_time = FILETIME(), FILETIME()
                kernel_t, user_t = FILETIME(), FILETIME()
                if not kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel_t),
                    ctypes.byref(user_t),
                ):
                    continue
                # 100-nanosecond ticks to seconds.
                cpu_seconds = (
                    _filetime_to_int(kernel_t) + _filetime_to_int(user_t)
                ) / 1e7
                memory_mb = _process_memory_mb(handle)

                percent = 0.0
                previous = self._prev_own.get(pid)
                if previous is not None:
                    prev_cpu, prev_at = previous
                    elapsed = now - prev_at
                    if elapsed > 0:
                        # Per cent of the whole machine, so it adds up against
                        # the CPU figure above rather than reading as 400%.
                        percent = round(
                            max(0.0, (cpu_seconds - prev_cpu) / elapsed / cores * 100), 1
                        )
                self._prev_own[pid] = (cpu_seconds, now)

                total_cpu += percent
                total_mb += memory_mb
                rows.append({"pid": pid, "cpu": percent, "memory_mb": round(memory_mb)})
            finally:
                kernel32.CloseHandle(handle)

        return (round(total_cpu, 1), round(total_mb), rows)

    def _throttle(self, now: float) -> tuple[bool, str]:
        """Has firmware limited the CPU recently?

        This is the signal that mattered on 17 Aug: the machine was not busy,
        it was *clamped*, and no amount of closing programs would have fixed it.
        Event 37 from Kernel-Processor-Power is Windows saying so.

        Expensive (it shells out), so it runs once a minute at most.
        """
        if not IS_WINDOWS or now - self._throttle_checked_at < 60:
            return self._throttle_state
        self._throttle_checked_at = now
        script = (
            "$e = Get-WinEvent -FilterHashtable @{LogName='System';"
            "ProviderName='Microsoft-Windows-Kernel-Processor-Power';Id=37;"
            "StartTime=(Get-Date).AddMinutes(-10)} "
            "-MaxEvents 1 -ErrorAction SilentlyContinue; "
            "if ($e) { 'THROTTLED ' + $e.TimeCreated.ToString('HH:mm:ss') }"
        )
        try:
            output = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return self._throttle_state
        if output.startswith("THROTTLED"):
            self._throttle_state = (
                True,
                f"Windows firmware limited CPU speed at {output.split()[-1]} "
                "— usually heat or a power limit, not load.",
            )
        else:
            self._throttle_state = (False, "")
        return self._throttle_state

    # -- sampling ----------------------------------------------------------- #

    def sample(self) -> Sample:
        now = time.time()
        cpu = self._cpu_percent()
        load, used, total, commit_used, commit_total = self._memory()
        free_gb, total_gb, disk_path = self._disk()
        own_cpu, own_mb, own_rows = self._own_usage(now)
        throttled, throttle_note = self._throttle(now)

        sample = Sample(
            at=now,
            cpu_percent=cpu,
            memory_percent=load,
            memory_used_gb=used,
            memory_total_gb=total,
            commit_used_gb=commit_used,
            commit_total_gb=commit_total,
            disk_free_gb=free_gb,
            disk_total_gb=total_gb,
            disk_path=disk_path,
            own_cpu_percent=own_cpu,
            own_memory_mb=own_mb,
            own_processes=own_rows,
            throttled=throttled,
            throttle_note=throttle_note,
        )
        sample.warnings = self._warnings(sample)
        return sample

    def _warnings(self, sample: Sample) -> list[dict]:
        """What to say, and how loudly.

        Every warning names a *cause* and an action. "CPU at 96%" is not useful
        on its own; "the test suite is using 71% of it, run it with -n 4" is.
        """
        out: list[dict] = []

        def add(level: str, code: str, message: str) -> None:
            out.append({"level": level, "code": code, "message": message})

        if sample.throttled:
            add("critical", "cpu_throttled", sample.throttle_note)

        if sample.cpu_percent is not None and self._sustained(
            "cpu_percent", CPU_WARN
        ):
            ours = sample.own_cpu_percent or 0.0
            share = (
                f" Gamira's own processes are {ours:.0f}% of it."
                if ours >= 10
                else " Almost none of it is Gamira."
            )
            level = "critical" if sample.cpu_percent >= CPU_CRITICAL else "warn"
            add(
                level,
                "cpu_high",
                f"CPU has been above {CPU_WARN:.0f}% for a while "
                f"(now {sample.cpu_percent:.0f}%).{share}",
            )

        if sample.memory_percent is not None and sample.memory_percent >= MEMORY_WARN:
            level = (
                "critical" if sample.memory_percent >= MEMORY_CRITICAL else "warn"
            )
            add(
                level,
                "memory_high",
                f"Memory is {sample.memory_percent:.0f}% full "
                f"({sample.memory_used_gb:.1f} of {sample.memory_total_gb:.1f} GB). "
                "Windows will start paging, which feels like the whole machine "
                "hanging.",
            )

        if sample.disk_free_gb is not None and sample.disk_total_gb:
            percent_free = sample.disk_free_gb / sample.disk_total_gb * 100
            low_gb = sample.disk_free_gb <= DISK_WARN_GB
            low_percent = percent_free <= DISK_WARN_PERCENT
            if low_gb or low_percent:
                critical = (
                    sample.disk_free_gb <= DISK_CRITICAL_GB
                    or percent_free <= DISK_CRITICAL_PERCENT
                )
                add(
                    "critical" if critical else "warn",
                    "disk_low",
                    f"{sample.disk_free_gb:.0f} GB free on {sample.disk_path} "
                    f"({percent_free:.0f}% of the drive). The page file and every "
                    "temp file live there, and Windows itself gets slow when it "
                    "runs out of room to work in.",
                )

        return out

    def _sustained(self, attribute: str, threshold: float) -> bool:
        """Has a reading been over the line for SUSTAIN_SECONDS?

        A build pegging every core for three seconds is not worth a warning; the
        same load for half a minute is where the machine starts to stutter.
        """
        with self._lock:
            recent = [
                s
                for s in self.samples
                if s.at >= time.time() - SUSTAIN_SECONDS
            ]
        if len(recent) < 3:
            return False
        values = [getattr(s, attribute) for s in recent]
        return all(v is not None and v >= threshold for v in values)

    # -- what the console reads --------------------------------------------- #

    def snapshot(self) -> dict:
        """The current reading plus a short trend, for the Health tab."""
        with self._lock:
            samples = list(self.samples)
        latest = samples[-1] if samples else None
        if latest is None:
            # Sample synchronously so the first page load is not empty.
            try:
                latest = self.sample()
            except Exception:
                return {"available": False, "reason": "no reading yet"}

        return {
            "available": True,
            "at": latest.at,
            "cpu": latest.cpu_percent,
            "memory_percent": latest.memory_percent,
            "memory_used_gb": latest.memory_used_gb,
            "memory_total_gb": latest.memory_total_gb,
            "commit_used_gb": latest.commit_used_gb,
            "commit_total_gb": latest.commit_total_gb,
            "disk_free_gb": latest.disk_free_gb,
            "disk_total_gb": latest.disk_total_gb,
            "disk_path": latest.disk_path,
            "own_cpu": latest.own_cpu_percent,
            "own_memory_mb": latest.own_memory_mb,
            "own_processes": latest.own_processes,
            "throttled": latest.throttled,
            "warnings": latest.warnings,
            "thresholds": {
                "cpu_warn": CPU_WARN,
                "cpu_critical": CPU_CRITICAL,
                "memory_warn": MEMORY_WARN,
                "memory_critical": MEMORY_CRITICAL,
                "disk_warn_gb": DISK_WARN_GB,
                "disk_critical_gb": DISK_CRITICAL_GB,
            },
            "trend": [
                {
                    "at": s.at,
                    "cpu": s.cpu_percent,
                    "memory": s.memory_percent,
                    "own_cpu": s.own_cpu_percent,
                }
                for s in samples[-60:]
            ],
        }


def _process_memory_mb(handle: int) -> float:
    """Working set for one process handle, or 0 if it cannot be read."""

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
    except (AttributeError, OSError):
        return 0.0
    return counters.WorkingSetSize / (1024**2) if ok else 0.0


# --------------------------------------------------------------------------- #
# Standalone use: python tools/sysmon.py
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover - a hand tool
    monitor = SystemMonitor(interval_seconds=2.0)
    monitor.start()
    print("Sampling. Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(2.0)
            snap = monitor.snapshot()
            if not snap.get("available"):
                continue
            print(
                f"cpu {snap['cpu']:>5}%   mem {snap['memory_percent']:>3}% "
                f"({snap['memory_used_gb']}/{snap['memory_total_gb']} GB)   "
                f"{snap['disk_path']} {snap['disk_free_gb']} GB free"
                + ("   THROTTLED" if snap["throttled"] else "")
            )
            for warning in snap["warnings"]:
                print(f"  [{warning['level']}] {warning['message']}")
    except KeyboardInterrupt:
        monitor.stop()
        print("\nstopped")
