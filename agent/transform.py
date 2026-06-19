from typing import Any

"""
Converts the nested dict returned by collector.collect_snapshot() into the
flat list of {metric_type, pid, value, unit, metadata} entries required by
the agent/server message contract.
"""
def flatten_snapshot(snapshot, dict[str, Any]) -> list[dict[str, Any]]:
	# cpu stats extract per core (percentage)
	for core_labels, percent in snapshot.get("cpu", {}).items():
		metrics.append({
            "metric_type": "cpu",
            "pid": None,
            "value": percent,
            "unit": "percent",
            "metadata": {"core": core_label},
			})

	# memory stats (in percentage/mb)
	for key, value in snapshot.get("memory", {}).items():
		unit = "percent" if key == "used_percent" else "mb"
        metrics.append({
            "metric_type": "memory",
            "pid": None,
            "value": value,
            "unit": unit,
            "metadata": {"field": key},
        })

    #disk stats
    for device, rates in snapshot.get("disk", {}).items():
		# for read mb/s
		metrics.append({
            "metric_type": "disk_io",
            "pid": None,
            "value": rates["read_mb_per_s"],
            "unit": "mb_per_s",
            "metadata": {"device": device, "direction": "read"},
        })
        # for write mb/s
        metrics.append({
            "metric_type": "disk_io",
            "pid": None,
            "value": rates["write_mb_per_s"],
            "unit": "mb_per_s",
            "metadata": {"device": device, "direction": "write"},
        })

    # network stats
    for iface, rates in snapshot.get("network", {}).items():
        # recieved kb/s
        metrics.append({
            "metric_type": "net_io",
            "pid": None,
            "value": rates["recv_kb_per_s"],
            "unit": "kb_per_s",
            "metadata": {"interface": iface, "direction": "recv"},
        })
        #sent kb/s
        metrics.append({
            "metric_type": "net_io",
            "pid": None,
            "value": rates["sent_kb_per_s"],
            "unit": "kb_per_s",
            "metadata": {"interface": iface, "direction": "sent"},
        })

    # processes
	for proc in snapshot.get("processes", []):
        metrics.append({
            "metric_type": "process",
            "pid": proc["pid"],
            "value": proc["cpu_percent"],
            "unit": "percent",
            "metadata": {
                "name": proc["name"],
                "memory_mb": proc["memory_mb"],
            },
        })
 
    return metrics