import time
from pathlib import Path
from .cpu import get_raw_ticks

def _get_process_snapshot() -> dict[int, dict]:
    """
    Raw single read of /proc/[pid]/status and /proc/[pid]/stat for all running processes.
    Returns a dict keyed by PID — this is the hash map from the technical design doc.
    O(1) PID lookup when correlating metrics, network connections, and anomalies later.
    """
    processes = {}
    proc_path = Path("/proc")

    for pid_dir in proc_path.iterdir():
        # /proc contains both PID directories (numeric) and other files — skip non-PIDs
        if not pid_dir.name.isdigit():
            continue

        pid = int(pid_dir.name)

        try:
            # --- /proc/[pid]/status: name and memory ---
            # same key:value format as /proc/meminfo — parse into a dict then extract what we need
            status = {}
            for line in (pid_dir / "status").read_text().splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    status[key.strip()] = val.strip()

            name = status.get("Name", "unknown")
            # VmRSS is physical RAM currently used by this process, in kB
            # some kernel threads have no VmRSS entry — default to 0
            vmrss_line = status.get("VmRSS", "0 kB")
            memory_kb = int(vmrss_line.split()[0])

            # --- /proc/[pid]/stat: cpu ticks ---
            # the line is one long space-separated string, but field 1 (process name)
            # is wrapped in parentheses and can contain spaces — e.g. "(My Process)"
            # so we can't naively split() and index by position
            # instead: find the last ')' and parse everything after it
            stat_line = (pid_dir / "stat").read_text()
            end = stat_line.rindex(")")           # last ')' handles names with spaces
            rest = stat_line[end + 2:].split()    # skip ') ', then split the rest
            # utime (field 14 in man page, 1-indexed) = rest[11] (0-indexed from after ')')
            # stime (field 15 in man page, 1-indexed) = rest[12]
            utime = int(rest[11])
            stime = int(rest[12])

            processes[pid] = {
                "pid":       pid,
                "name":      name,
                "memory_kb": memory_kb,
                "cpu_ticks": utime + stime,  # total cpu ticks consumed by this process
            }

        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            # processes can die between iterdir() and our read — this is normal, just skip
            continue

    return processes


def read_process_stats(interval: float = 1.0) -> list[dict]:
    """
    Returns a list of running processes with CPU usage % and memory.
    Sorted by CPU usage descending — top consumers first.
    Same delta pattern as CPU/disk/network: two snapshots, one sleep.

    CPU % denominator: we use the total system tick delta from get_raw_ticks() so that
    per-process % is relative to total system capacity — a process on 1 of 4 cores
    at 100% reports 25%, consistent with how htop/top report it.
    """
    # take system tick snapshot alongside process snapshot so denominators are aligned
    sys_ticks_1 = get_raw_ticks()
    proc_snap_1 = _get_process_snapshot()

    time.sleep(interval)

    sys_ticks_2 = get_raw_ticks()
    proc_snap_2 = _get_process_snapshot()

    # compute total system tick delta across all cores using the aggregate 'cpu' line
    # this is the same denominator used in read_cpu_stats()
    s1 = sys_ticks_1["cpu"]
    s2 = sys_ticks_2["cpu"]
    total_idle   = (s2["idle"] + s2["iowait"]) - (s1["idle"] + s1["iowait"])
    total_non_idle = (
        (s2["user"] + s2["nice"] + s2["system"] + s2["irq"] + s2["softirq"] + s2["steal"]) -
        (s1["user"] + s1["nice"] + s1["system"] + s1["irq"] + s1["softirq"] + s1["steal"])
    )
    total_delta = total_idle + total_non_idle  # total elapsed ticks across all cores

    results = []

    for pid in proc_snap_1:
        if pid not in proc_snap_2:
            continue  # process exited during the interval — skip it

        p1 = proc_snap_1[pid]
        p2 = proc_snap_2[pid]

        tick_delta = p2["cpu_ticks"] - p1["cpu_ticks"]  # ticks this process consumed

        # cpu % = (ticks this process used) / (total system ticks elapsed) * 100
        # total_delta already spans all cores, so a process maxing one of 4 cores → ~25%
        if total_delta > 0:
            cpu_percent = round((tick_delta / total_delta) * 100, 2)
        else:
            cpu_percent = 0.0

        results.append({
            "pid":         pid,
            "name":        p2["name"],
            "cpu_percent": cpu_percent,
            "memory_kb":   p2["memory_kb"],
            "memory_mb":   round(p2["memory_kb"] / 1024, 2),
        })

    # sort by cpu_percent descending — top consumers first
    return sorted(results, key=lambda p: p["cpu_percent"], reverse=True)