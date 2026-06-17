import json
import time
import datetime
from pathlib import Path

# ─────────────────────────────────────────────
# CPU
# ─────────────────────────────────────────────

def get_raw_ticks() -> dict[str, dict[str, int]]:
    """
    Parse /proc/stat and return raw cumulative CPU tick counts since boot.
    Call twice with a sleep in between to compute meaningful usage percentages.
    """
    columns = ["user", "nice", "system", "idle", "iowait",
               "irq", "softirq", "steal", "guest", "guest_nice"]
    '''
    user: the time spent on processes in the user space
    nice: these processes have low priority (hence a high nice value) also being executed in the background in the user space
    system: the time spent on processes in the kernal space
    idle: time spent waitin for any disk I/O 
    iowait: time spent waiting for for an I/O operation, high iowait means the storage is bottlenecking the CPU
    irq: the time spent servicing hardware interupts (network card recieves a packet or a keystroke happens), they interrupt the CPU right away
    softirq: the time spent servicing software interrupts (less critical than irq)
    steal: time virtual CPU wanted to execute but the underlying hyperavisor was busy servicing the other guest on the host
    guest: the time spent running a virtual CPU for a guest OS
    guest_nice: time spent servicing low priority processes for guest OS
     '''
    stats = {}

    path = Path("/proc/stat")
    with path.open("r") as file:
        for line in file:
            if not line.startswith("cpu"): # skip non-cpu lines
                continue

            parts = line.split()
            cpu_name = parts[0] # 'cpu', 'cpu0', 'cpu1', etc.

            # convert tick values to ints and zip with column names into a dict
            values = [int(val) for val in parts[1:]]
            stats[cpu_name] = dict(zip(columns, values))

    return stats


def read_cpu_stats(interval: float = 1.0) -> dict[str, float]:
    """
    Return CPU usage % for overall + each core.
    Takes two /proc/stat snapshots `interval` seconds apart to compute delta.
    """
    stat1 = get_raw_ticks()
    time.sleep(interval)
    stat2 = get_raw_ticks()

    percentages = {}

    for cpu in stat1:
        if cpu not in stat2:
            continue

        s1 = stat1[cpu]
        s2 = stat2[cpu]

        # idle time = idle + iowait (CPU is blocked, not doing useful work)
        idle1 = s1["idle"] + s1["iowait"]
        idle2 = s2["idle"] + s2["iowait"]

        # non-idle = everything else summed together
        non_idle1 = s1["user"] + s1["nice"] + s1["system"] + s1["irq"] + s1["softirq"] + s1["steal"]
        non_idle2 = s2["user"] + s2["nice"] + s2["system"] + s2["irq"] + s2["softirq"] + s2["steal"]

        delta_total = (idle2 + non_idle2) - (idle1 + non_idle1)
        delta_idle = idle2 - idle1

        if delta_total > 0:
            percentages[cpu] = round(((delta_total - delta_idle) / delta_total) * 100, 2)
        else:
            percentages[cpu] = 0.0

    return percentages


# ─────────────────────────────────────────────
# Memory
# ─────────────────────────────────────────────

def read_memory_stats() -> dict[str, int | float]:
    """
    Parse /proc/meminfo to extract total, available, and used memory.
    /proc/meminfo reflects current state (not cumulative), so no delta needed.
    Each line format: 'FieldName:   value kB'
    """
    mem = {}

    path = Path("/proc/meminfo")
    with path.open("r") as file:
        for line in file:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":") # strip trailing colon from field name
                mem[key] = int(parts[1]) # value is always in kB

    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)

    return {
        "total_mb":     total // 1024,
        "available_mb": available // 1024,
        "used_mb":      (total - available) // 1024,
        "used_percent": round((total - available) / total * 100, 2),
    }


# ─────────────────────────────────────────────
# Disk
# ─────────────────────────────────────────────

def _get_disk_snapshot() -> dict[str, dict[str, int]]:
    """
    Raw single read of /proc/diskstats.
    Skips partitions (sda1, nvme0n1p1, etc.) — only tracks physical devices.
    Extracted as a top-level function so collect_snapshot() controls the sleep.
    """
    stats = {}
    path = Path("/proc/diskstats")

    with path.open("r") as file:
        for line in file:
            parts = line.split()
            device = parts[2]

            # partitions end in a digit but are not the base device (e.g. nvme0n1)
            if device[-1].isdigit() and not device.endswith("0"):
                continue

            stats[device] = {
                "sectors_read":    int(parts[5]),
                "sectors_written": int(parts[9]),
            }

    return stats


# ─────────────────────────────────────────────
# Network
# ─────────────────────────────────────────────

def _get_net_snapshot() -> dict[str, dict[str, int]]:
    """
    Raw single read of /proc/net/dev.
    Skips loopback (lo). Bytes are cumulative since boot — delta needed for rates.
    Extracted as a top-level function so collect_snapshot() controls the sleep.
    """
    stats = {}
    path = Path("/proc/net/dev")

    with path.open("r") as file:
        for line in file:
            line = line.strip()
            if ":" not in line: # skip the two header lines
                continue

            interface, data = line.split(":", 1)
            interface = interface.strip()

            if interface == "lo": # loopback is not useful to monitor
                continue

            parts = data.split()
            stats[interface] = {
                "bytes_recv": int(parts[0]), # receive bytes at index 0
                "bytes_sent": int(parts[8]), # transmit bytes at index 8
            }

    return stats

# ─────────────────────────────────────────────
# Processes
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# Unified snapshot
# ─────────────────────────────────────────────

def collect_snapshot(interval: float = 1.0) -> dict:
    """
    Single structured snapshot. One sleep for all delta-based metrics.
    This dict is what eventually gets written to the ring buffer and TimescaleDB.
    """
    SECTOR_SIZE = 512  # bytes per sector, fixed on Linux

    # --- first snapshots ---
    cpu_first     = get_raw_ticks()
    disk_first    = _get_disk_snapshot()
    net_first     = _get_net_snapshot()
    process_first = _get_process_snapshot()  # added

    # one sleep covers all delta-based metrics
    time.sleep(interval)

    # --- second snapshots ---
    cpu_second     = get_raw_ticks()
    disk_second    = _get_disk_snapshot()
    net_second     = _get_net_snapshot()
    process_second = _get_process_snapshot()  # added

    # --- compute cpu percentages ---
    cpu_result = {}
    for cpu in cpu_first:
        if cpu not in cpu_second:
            continue
        s1, s2 = cpu_first[cpu], cpu_second[cpu]
        idle1      = s1["idle"] + s1["iowait"]
        idle2      = s2["idle"] + s2["iowait"]
        non_idle1  = s1["user"] + s1["nice"] + s1["system"] + s1["irq"] + s1["softirq"] + s1["steal"]
        non_idle2  = s2["user"] + s2["nice"] + s2["system"] + s2["irq"] + s2["softirq"] + s2["steal"]
        delta_total = (idle2 + non_idle2) - (idle1 + non_idle1)
        delta_idle  = idle2 - idle1
        cpu_result[cpu] = round(((delta_total - delta_idle) / delta_total) * 100, 2) if delta_total > 0 else 0.0

    # --- compute disk deltas ---
    disk_result = {}
    for device in disk_first:
        if device not in disk_second:
            continue
        read_delta  = disk_second[device]["sectors_read"]    - disk_first[device]["sectors_read"]
        write_delta = disk_second[device]["sectors_written"] - disk_first[device]["sectors_written"]
        disk_result[device] = {
            "read_mb_per_s":  round((read_delta  * SECTOR_SIZE) / (1024 ** 2) / interval, 3),
            "write_mb_per_s": round((write_delta * SECTOR_SIZE) / (1024 ** 2) / interval, 3),
        }

    # --- compute network deltas ---
    net_result = {}
    for iface in net_first:
        if iface not in net_second:
            continue
        recv_delta = net_second[iface]["bytes_recv"] - net_first[iface]["bytes_recv"]
        sent_delta = net_second[iface]["bytes_sent"] - net_first[iface]["bytes_sent"]
        net_result[iface] = {
            "recv_kb_per_s": round(recv_delta / 1024 / interval, 3),
            "sent_kb_per_s": round(sent_delta / 1024 / interval, 3),
        }

    # --- compute per-process cpu % using system tick delta as denominator ---
    # reuse the cpu_first/cpu_second aggregate 'cpu' line already computed above
    s1 = cpu_first["cpu"]
    s2 = cpu_second["cpu"]
    total_idle     = (s2["idle"] + s2["iowait"]) - (s1["idle"] + s1["iowait"])
    total_non_idle = (
        (s2["user"] + s2["nice"] + s2["system"] + s2["irq"] + s2["softirq"] + s2["steal"]) -
        (s1["user"] + s1["nice"] + s1["system"] + s1["irq"] + s1["softirq"] + s1["steal"])
    )
    total_delta = total_idle + total_non_idle  # total elapsed ticks across all cores

    process_result = []
    for pid in process_first:
        if pid not in process_second:
            continue  # process exited during interval — skip
        p1, p2 = process_first[pid], process_second[pid]
        tick_delta  = p2["cpu_ticks"] - p1["cpu_ticks"]
        cpu_percent = round((tick_delta / total_delta) * 100, 2) if total_delta > 0 else 0.0
        # skip kernel threads — they have no memory and will never show CPU activity
        if p2["memory_kb"] == 0 and p2["cpu_ticks"] == 0:
            continue
            
        process_result.append({
            "pid":         pid,
            "name":        p2["name"],
            "cpu_percent": cpu_percent,
            "memory_kb":   p2["memory_kb"],
            "memory_mb":   round(p2["memory_kb"] / 1024, 2),
        })

    # sort by cpu_percent descending — top consumers first
    process_result.sort(key=lambda p: p["cpu_percent"], reverse=True)

    return {
        "timestamp": time.time(),
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "cpu":       cpu_result,
        "memory":    read_memory_stats(),  # current state — no delta needed
        "disk":      disk_result,
        "network":   net_result,
        "processes": process_result,       # added
    }

if __name__ == "__main__":
    print("Collecting snapshot...")
    snapshot = collect_snapshot()
    print(json.dumps(snapshot, indent=2))