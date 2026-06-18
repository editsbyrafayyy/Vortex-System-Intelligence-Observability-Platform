import time
import datetime
import json

from .readers.cpu       import get_raw_ticks
from .readers.memory    import read_memory_stats
from .readers.disk      import _get_disk_snapshot
from .readers.network   import _get_net_snapshot
from .readers.processes import _get_process_snapshot

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