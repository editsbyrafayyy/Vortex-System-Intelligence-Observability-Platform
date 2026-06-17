from pathlib import Path

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
