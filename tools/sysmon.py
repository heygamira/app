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

if IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    # Declared, because the default return type is a 32-bit int: a HANDLE coming
    # back through that is truncated or sign-extended on x64. Handles happen to
    # fit in 32 bits today, so the bug is silent rather than absent — and a
    # negative handle handed back to CloseHandle fails quietly.
    _k32 = ctypes.windll.kernel32
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

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


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _filetime_to_int(value: FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _parent_map() -> dict[int, int]:
    """Every live process and its parent, straight from kernel32.

    Needed because the interesting processes are grandchildren. `npm run dev`
    is a shim whose node child is the actual Vite server, and `uvicorn --reload`
    is a supervisor whose child is the actual API. Measuring only the processes
    this runner spawned therefore reported a few megabytes and nought per cent
    for a stack using gigabytes — the Health tab was watching the wrong things.

    Cheap: one snapshot, no subprocess, no PowerShell.
    """
    if not IS_WINDOWS:
        return {}
    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE:
        return {}
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snapshot, ctypes.byref(entry)):
            return {}
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _with_descendants(roots: list[int]) -> list[int]:
    """The tracked processes plus everything living underneath them."""
    parents = _parent_map()
    if not parents:
        return list(roots)
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        children.setdefault(parent, []).append(pid)

    found: list[int] = []
    seen: set[int] = set()
    queue = [pid for pid in roots if pid]
    while queue:
        pid = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        found.append(pid)
        queue.extend(children.get(pid, ()))
    return found


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
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sysmon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling, and be genuinely restartable afterwards.

        This used to only set the event, leaving `_thread` set and `_stop` set, so
        a later `start()` was a silent no-op — the monitor was dead with nothing
        to say so.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.interval + 1.0)
        self._thread = None

    def track(self, pids: list[int]) -> None:
        """Tell the monitor which processes belong to this run."""
        with self._lock:
            self._own_pids = list(pids)

    def _run(self) -> None:
        # Prime the CPU delta so the first real sample is not nonsense, and take
        # one reading straight away without the PowerShell probe. Without this the
        # first three seconds have no sample at all, and the console's first
        # request for health would take one on the HTTP thread instead.
        self._cpu_percent()
        self._record(probe_throttle=False)
        while not self._stop.wait(self.interval):
            self._record()

    def _record(self, probe_throttle: bool = True) -> Sample | None:
        try:
            sample = self.sample(probe_throttle=probe_throttle)
        except Exception:
            # A monitor must never be the reason the stack stops. A failed
            # sample is skipped; the next one usually works.
            return None
        with self._lock:
            self.samples.append(sample)
            if len(self.samples) > self.history_size:
                del self.samples[: -self.history_size]
        return sample

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

    def _one_process(
        self, pid: int, now: float, cores: int
    ) -> tuple[float, float] | None:
        """CPU per cent and resident megabytes for one process, or None if gone."""
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            self._prev_own.pop(pid, None)
            return None
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
                return None
            # 100-nanosecond ticks to seconds.
            cpu_seconds = (_filetime_to_int(kernel_t) + _filetime_to_int(user_t)) / 1e7
            memory_mb = _process_memory_mb(handle)
        finally:
            kernel32.CloseHandle(handle)

        percent = 0.0
        previous = self._prev_own.get(pid)
        if previous is not None:
            prev_cpu, prev_at = previous
            elapsed = now - prev_at
            if elapsed > 0:
                # Per cent of the whole machine, so it adds up against the CPU
                # figure above rather than reading as 400%.
                percent = round(
                    max(0.0, (cpu_seconds - prev_cpu) / elapsed / cores * 100), 1
                )
        self._prev_own[pid] = (cpu_seconds, now)
        return (percent, memory_mb)

    def _own_usage(self, now: float) -> tuple[float, float, list[dict]]:
        """CPU and memory for this run's own processes, including their children.

        Separating them from the machine total is the useful part: "the machine is
        at 95 per cent" and "*we* are at 95 per cent" call for different
        reactions. Counting descendants is what makes the answer true — `npm run
        dev` is a shim and the node process underneath it is the actual Vite
        server, `uvicorn --reload` is a supervisor and its child is the actual
        API. Measuring only the processes this runner spawned reported four
        megabytes for a Vite server and nought per cent for everything, which was
        worse than showing nothing.
        """
        with self._lock:
            roots = list(self._own_pids)
        if not IS_WINDOWS or not roots:
            with self._lock:
                self._prev_own.clear()
            return (0.0, 0.0, [])

        cores = os.cpu_count() or 1
        total_cpu = 0.0
        total_mb = 0.0
        rows: list[dict] = []
        alive: set[int] = set()

        # One tree per tracked process, reported as one row: the interesting unit
        # is "the dashboard server", not "npm and the node it started".
        for root in roots:
            tree = _with_descendants([root])
            tree_cpu = 0.0
            tree_mb = 0.0
            counted = 0
            for pid in tree:
                reading = self._one_process(pid, now, cores)
                if reading is None:
                    continue
                alive.add(pid)
                tree_cpu += reading[0]
                tree_mb += reading[1]
                counted += 1
            if not counted:
                continue
            total_cpu += tree_cpu
            total_mb += tree_mb
            rows.append(
                {
                    "pid": root,
                    "cpu": round(tree_cpu, 1),
                    "memory_mb": round(tree_mb),
                    "processes": counted,
                }
            )

        # Forget processes no longer being tracked, so the previous-tick table
        # does not keep every pid this run has ever spawned.
        for pid in [pid for pid in self._prev_own if pid not in alive]:
            self._prev_own.pop(pid, None)

        return (round(total_cpu, 1), round(total_mb), rows)

    def _throttle(self, now: float, probe: bool = True) -> tuple[bool, str]:
        """Has firmware limited the CPU recently?

        This is the signal that mattered on 17 Aug: the machine was not busy,
        it was *clamped*, and no amount of closing programs would have fixed it.
        Event 37 from Kernel-Processor-Power is Windows saying so.

        Expensive (it shells out to PowerShell), so it runs once a minute at most,
        and callers who cannot afford to block at all pass ``probe=False`` to take
        whatever the last check found.
        """
        if not probe or not IS_WINDOWS or now - self._throttle_checked_at < 60:
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

    def sample(self, probe_throttle: bool = True) -> Sample:
        now = time.time()
        cpu = self._cpu_percent()
        load, used, total, commit_used, commit_total = self._memory()
        free_gb, total_gb, disk_path = self._disk()
        own_cpu, own_mb, own_rows = self._own_usage(now)
        throttled, throttle_note = self._throttle(now, probe=probe_throttle)

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

    def snapshot(self, probe_throttle: bool = False) -> dict:
        """The current reading plus a short trend, for the Health tab.

        Never runs the PowerShell throttle probe unless asked: this is called from
        the console's HTTP thread, and a request for health that can block for
        fifteen seconds is its own kind of stall. The sampler thread does that
        check on its own cadence and leaves the answer here.
        """
        with self._lock:
            samples = list(self.samples)
        latest = samples[-1] if samples else None
        if latest is None:
            # Nothing recorded yet — take one now, through _record so it is stored
            # under the lock rather than mutating the tick counters from here and
            # being thrown away.
            latest = self._record(probe_throttle=probe_throttle)
            if latest is None:
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
                # Exported so the page stops improvising them. It had been
                # deriving "1% free" from disk_critical_gb / 10 and hard-coding
                # 12, which is how the alarm and the meter beside it could
                # disagree about the same drive.
                "disk_warn_percent": DISK_WARN_PERCENT,
                "disk_critical_percent": DISK_CRITICAL_PERCENT,
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
        probe = ctypes.windll.psapi.GetProcessMemoryInfo
        probe.restype = wintypes.BOOL
        probe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        ok = probe(handle, ctypes.byref(counters), counters.cb)
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
    # A reading that could not be taken is None, and formatting None with a width
    # raises — so the tool would crash on exactly the machine it is meant to
    # diagnose. Say "—" instead.
    def figure(value: object, width: int = 5) -> str:
        return f"{'—' if value is None else value:>{width}}"

    try:
        while True:
            time.sleep(2.0)
            snap = monitor.snapshot(probe_throttle=True)
            if not snap.get("available"):
                print(f"  no reading: {snap.get('reason', 'unavailable')}")
                continue
            print(
                f"cpu {figure(snap['cpu'])}%   mem {figure(snap['memory_percent'], 3)}% "
                f"({snap['memory_used_gb']}/{snap['memory_total_gb']} GB)   "
                f"{snap['disk_path']} {snap['disk_free_gb']} GB free"
                + ("   THROTTLED" if snap["throttled"] else "")
            )
            for warning in snap["warnings"]:
                print(f"  [{warning['level']}] {warning['message']}")
    except KeyboardInterrupt:
        monitor.stop()
        print("\nstopped")
