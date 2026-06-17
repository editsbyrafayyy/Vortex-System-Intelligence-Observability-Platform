import time
from pathlib import Path

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