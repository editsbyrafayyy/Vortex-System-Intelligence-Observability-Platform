import json
from . import collect_snapshot

print("Collecting snapshot...")
snapshot = collect_snapshot()
print(json.dumps(snapshot, indent=2))