import json
import time
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
# Unified snapshot
# ─────────────────────────────────────────────

def collect_snapshot(interval: float = 1.0) -> dict:
    """
    Collect a single structured snapshot of current system state.
    All three delta-based metrics share one sleep — avoids 3x the wait time
    if each reader slept independently.
    This dict is what eventually gets written to the ring buffer and TimescaleDB.
    """
    SECTOR_SIZE = 512  # bytes per sector, fixed on Linux

    # ── first snapshots (all taken before the sleep) ──
    cpu_first  = get_raw_ticks()
    disk_first = _get_disk_snapshot()
    net_first  = _get_net_snapshot()

    time.sleep(interval)

    # ── second snapshots ──
    cpu_second  = get_raw_ticks()
    disk_second = _get_disk_snapshot()
    net_second  = _get_net_snapshot()

    # ── CPU: compute usage % from tick deltas ──
    cpu_result = {}
    for cpu in cpu_first:
        if cpu not in cpu_second:
            continue
        s1, s2 = cpu_first[cpu], cpu_second[cpu]
        idle1    = s1["idle"] + s1["iowait"]
        idle2    = s2["idle"] + s2["iowait"]
        non_idle1 = s1["user"] + s1["nice"] + s1["system"] + s1["irq"] + s1["softirq"] + s1["steal"]
        non_idle2 = s2["user"] + s2["nice"] + s2["system"] + s2["irq"] + s2["softirq"] + s2["steal"]
        delta_total = (idle2 + non_idle2) - (idle1 + non_idle1)
        delta_idle  = idle2 - idle1
        cpu_result[cpu] = round(((delta_total - delta_idle) / delta_total) * 100, 2) if delta_total > 0 else 0.0

    # ── Disk: convert sector deltas to MB/s ──
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

    # ── Network: convert byte deltas to KB/s ──
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

    return {
        "timestamp": time.time(),
        "cpu":       cpu_result,
        "memory":    read_memory_stats(), # current state — no delta needed
        "disk":      disk_result,
        "network":   net_result,
    }


if __name__ == "__main__":
    print("Collecting snapshot...")
    snapshot = collect_snapshot()
    print(json.dumps(snapshot, indent=2))