import json
import time
from pathlib import Path


def get_raw_ticks() -> dict[str, dict[str, int]]: # we are returning cpu n and then the inner dict (name stat name (str) followed by value (int))
    """ Parse /proc/stat to extract CPU usage percentages. /proc/stat gives cumulative CPU ticks since boot — you need two snapshots and a delta to calculate actual usage %.
    Returns raw tick counts on first call; call twice with a sleep in between to get meaningful percentages."""

    columns = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"]
    stats = {}

    path = Path("/proc/stat") # we use the file where the results are stored as the path
    with path.open("r") as file: # open the file as read only 
        for f in file:
            if not f.startswith("cpu"): # if the line doesn't start with cpu we skip the line
                continue
        
            parts = f.split() # split the line as space as the delimiter
            cpuName = parts[0] # the output starts with the number of the cpu (cpu 1/2/3/4/etc)
            values = []

            for val in parts[1:]: # we skip the CPU name and start from the first metric
                convertedVal = int(val) # we convert that metric into int
                values.append(convertedVal) # then append that value in the list

            ''' we now use zip to combine 2 lists into 1, using columns as the key and values as well the values in the dict
            all of it is then stored into a nested dict stats where the stats for each cpu are stored in the dict '''
            stats[cpuName] = dict(zip(columns, values)) 

    return stats

def read_cpu_stats(interval: float=0.1) -> dict[str, float]: # Fixed 'string' to 'str'
    stat1 = get_raw_ticks()
    time.sleep(interval)
    stat2 = get_raw_ticks()

    percentages = {}

    for cpu in stat1:
        if cpu not in stat2:
            continue

        s1 = stat1[cpu]
        s2 = stat2[cpu]

        # idle time comprises of idle + iowait
        idle1 = s1["idle"] + s1["iowait"]
        idle2 = s2["idle"] + s2["iowait"]

        # while the rest of stats count as non-idle times, so we add them all together
        non_idle1 = s1["user"] + s1["nice"] + s1["system"] + s1["irq"] + s1["softirq"] + s1["steal"]
        non_idle2 = s2["user"] + s2["nice"] + s2["system"] + s2["irq"] + s2["softirq"] + s2["steal"]

        total1 = idle1 + non_idle1
        total2 = idle2 + non_idle2

        delta_total = total2 - total1
        delta_idle = idle2 - idle1

        if delta_total > 0:
            usage = ((delta_total - delta_idle) / delta_total) * 100
            percentages[cpu] = round(usage, 2)
        else:
            percentages[cpu] = 0.0

    return percentages

def read_memory_stats() -> dict[str,int]:
    """Parse /proc/meminfo to extract total, available, used memory.Each line is: 'FieldName: value kB'"""
    memStats = {}

    path = Path("/proc/meminfo")
    with path.open("r") as file:
        for f in file:
            parts = f.split() #split on spaces
            if len(parts) >= 2:
                key = parts[0].rstrip(":") # we split the name of the mem stat and store it in key using right strip
                memStats[key] = int(parts[1]) # then in the dict use key as the key and stats as the val for the dict

    totalMemory = memStats.get("MemTotal", 0) # we use exact names MemTotal to get the value from the dictionary (avoids crashing if we use .get)
    AvailableMemory = memStats.get("MemAvailable", 0)

    return {
    "total_mb": totalMemory // 1024,
    "available_mb": AvailableMemory // 1024,
    "used_mb": (totalMemory - AvailableMemory) // 1024,
    "used_percent": round((totalMemory - AvailableMemory) / totalMemory * 100, 2),
    }


def read_network_stats(interval: float = 1.0) -> dict[str, dict[str, float]]: # same parameters as cpu reader
    """
    Parse /proc/net/dev to get network throughput in KB/s per interface.
    Skips loopback (lo). Same delta pattern as CPU and disk.
    """

    def _snapshot() -> dict[str, dict[str, int]]: # nested function
        stats = {}
        path = Path("/proc/net/dev") # the path for where the contents are stored
        with path.open("r") as file:
            for line in file:
                line = line.strip()
                if ":" not in line:  # skip header lines
                    continue
                interface, data = line.split(":", 1) # split the line and store into parts
                interface = interface.strip()
                if interface == "lo":  # skip loopback
                    continue
                parts = data.split()
                stats[interface] = { # for a specific interface we store the recieved and sent bytes 
                    "bytes_recv": int(parts[0]),
                    "bytes_sent": int(parts[8]),
                }
        return stats

    first = _snapshot()
    time.sleep(interval)
    second = _snapshot()

    result = {}
    for iface in first:
        if iface not in second: # we need to make sure that they exist in both the first and the second chunk
            continue
        recv_delta = second[iface]["bytes_recv"] - first[iface]["bytes_recv"] # for rec we need to find the diff 
        sent_delta = second[iface]["bytes_sent"] - first[iface]["bytes_sent"]
        result[iface] = {
            "recv_kb_per_s": round(recv_delta / 1024 / interval, 3), # we convert the rec/sent into kb/s
            "sent_kb_per_s": round(sent_delta / 1024 / interval, 3),
        }
    return result # then return the result

def collect_snapshot() -> dict:
    """Returns a single structured snapshot of current system state.This is what eventually gets written to the ring buffer and then TimescaleDB."""
    return {
        "timestamp": time.time(),
        "cpu": read_cpu_stats(),
        "memory": read_memory_stats(),
    }


if __name__ == "__main__":
    snapshot = collect_snapshot()
    print(json.dumps(snapshot, indent=2))