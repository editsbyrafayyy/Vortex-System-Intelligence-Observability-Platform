"""
Shared message contract between agent and worker.
Both sides import from here — this is the schema_version 1 protocol.
Never change field names without bumping schema_version.
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    metric_type: str                     # 'cpu', 'memory', 'disk_io', 'net_io', 'process'
    pid: int | None = None               # None for system-wide metrics
    process_name: str | None = None
    value: float
    unit: str                            # 'percent', 'bytes', 'bytes_per_sec', etc.
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricPayload(BaseModel):
    schema_version: int = 1
    host_id: str                         # 'local' until Phase 7; UUID or hostname after
    agent_id: str                        # UUIDv4 identifying this agent process instance
    collected_at: datetime
    metrics: list[MetricSample]