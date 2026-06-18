import json
import psutil
import os
from . import collect_snapshot

def measure_overhead(interval: float, samples: int = 5):
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(interval=None)  # first call is always 0.0, throw it away

    readings = []
    for _ in range(samples):
        collect_snapshot(interval=interval)
        readings.append({
            "cpu_percent": proc.cpu_percent(interval=None),
            "rss_mb": round(proc.memory_info().rss / 1024**2, 2),
        })

    avg_cpu = round(sum(r["cpu_percent"] for r in readings) / len(readings), 2)
    avg_rss = round(sum(r["rss_mb"]      for r in readings) / len(readings), 2)
    print(f"interval={interval}s  avg_cpu={avg_cpu}%  avg_rss={avg_rss}MB")

for interval in [1.0, 5.0, 15.0]:
    measure_overhead(interval)

print("Collecting snapshot...")
snapshot = collect_snapshot()
print(json.dumps(snapshot, indent=2))