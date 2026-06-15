import json
import time
from pathlib import Path


def read_cpu_stats() -> dict[str, dict[str, int]]: # we are returning cpu n and then the inner dict (name stat name (str) followed by value (int))
    """ Parse /proc/stat to extract CPU usage percentages. /proc/stat gives cumulative CPU ticks since boot — you need two snapshots and a delta to calculate actual usage %.
    Returns raw tick counts on first call; call twice with a sleep in between to get meaningful percentages."""

    columns = ["user", "nice", " system", "idle", "iowait", "irq", "softirq", " steal", "guest", "guest_nice"]
    stats = {}

    path = Path("/proc/stat")
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

    return {"Total": totalMemory,"Available memory": AvailableMemory,"Used":totalMemory - AvailableMemory}


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