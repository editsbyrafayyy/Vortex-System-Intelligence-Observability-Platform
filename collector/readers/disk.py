from pathlib import Path

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