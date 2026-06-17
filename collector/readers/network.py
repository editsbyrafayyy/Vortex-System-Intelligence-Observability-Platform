from pathlib import Path

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
