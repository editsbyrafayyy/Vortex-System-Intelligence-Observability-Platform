import argparse
import json
import os
import time

import psutil

from . import collect_snapshot

DEFAULT_INTERVAL = float(os.getenv("COLLECTOR_INTERVAL", 5.0))

def measure_overhead(interval: float, samples: int = 5) -> None:
    """Print average CPU and RSS overhead at a given polling interval."""
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(interval=None)  # first call is always 0.0 — discard it

    readings = []
    for _ in range(samples):
        collect_snapshot(interval=interval)
        readings.append({
            "cpu_percent": proc.cpu_percent(interval=None),
            "rss_mb": round(proc.memory_info().rss / 1024 ** 2, 2),
        })

    avg_cpu = round(sum(r["cpu_percent"] for r in readings) / len(readings), 2)
    avg_rss = round(sum(r["rss_mb"] for r in readings) / len(readings), 2)
    print(f"interval={interval}s  avg_cpu={avg_cpu}%  avg_rss={avg_rss}MB")


def run_once(interval: float) -> None:
    """Collect a single snapshot and print it as JSON."""
    print("Collecting snapshot...")
    snapshot = collect_snapshot(interval=interval)
    print(json.dumps(snapshot, indent=2))


def run_watch(interval: float) -> None:
    """
    Continuously collect snapshots, printing each one as JSON.
    Each snapshot is separated by a blank line for readability.
    Ctrl-C exits cleanly.
    """
    print(f"Watching — polling every {interval}s  (Ctrl-C to stop)\n")
    try:
        while True:
            snapshot = collect_snapshot(interval=interval)
            print(json.dumps(snapshot, indent=2))
            print()  # blank line between snapshots
    except KeyboardInterrupt:
        print("\nStopped.")


def run_benchmark() -> None:
    """Re-run the overhead benchmark across the three canonical intervals."""
    print("Running overhead benchmark (5 samples per interval)...\n")
    for ivl in [1.0, 5.0, 15.0]:
        measure_overhead(ivl)



def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m collector",
        description="Vortex collector — read system metrics from /proc.",
    )

    # optional interval flag shared by once + watch modes
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=DEFAULT_INTERVAL,
        metavar="SECONDS",
        help=f"polling interval in seconds (default: {DEFAULT_INTERVAL})",
    )

    # mutually exclusive mode flags
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--watch", "-w",
        action="store_true",
        help="continuously print snapshots until Ctrl-C",
    )
    mode.add_argument(
        "--benchmark", "-b",
        action="store_true",
        help="measure collector CPU/memory overhead at 1s, 5s, and 15s intervals",
    )

    args = parser.parse_args()

    if args.benchmark:
        run_benchmark()
    elif args.watch:
        run_watch(args.interval)
    else:
        run_once(args.interval)


if __name__ == "__main__":
    main()