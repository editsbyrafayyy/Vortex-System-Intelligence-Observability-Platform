-- =============================================================================
-- Vortex — database initialisation
-- Applied automatically by TimescaleDB on first container boot.
-- Do NOT run this manually against a live database — it is idempotent but
-- the hypertable conversion will error if the table already contains data.
-- =============================================================================

-- Enable the TimescaleDB extension (safe to call if already enabled)
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- =============================================================================
-- TimescaleDB — metrics hypertable
-- =============================================================================

CREATE TABLE IF NOT EXISTS metrics (
    time          TIMESTAMPTZ      NOT NULL,
    host_id       TEXT             NOT NULL DEFAULT 'local',
    metric_type   TEXT             NOT NULL,   -- 'cpu' | 'memory' | 'disk_io' | 'net_io' | 'process'
    pid           INTEGER,                     -- NULL for system-wide metrics
    process_name  TEXT,
    value         DOUBLE PRECISION NOT NULL,
    unit          TEXT             NOT NULL,
    metadata      JSONB                        -- flexible extra fields (e.g. container_id, device name)
);

-- Convert to a hypertable partitioned by time (7-day chunks is the TimescaleDB default)
-- The IF NOT EXISTS guard means re-running this file is safe.
SELECT create_hypertable('metrics', 'time', if_not_exists => TRUE);

-- Composite index for the most common query pattern: a specific host + metric type
-- over a time range (what every dashboard chart uses).
CREATE INDEX IF NOT EXISTS idx_metrics_host_type_time
    ON metrics (host_id, metric_type, time DESC);

-- Sparse index for per-process history queries — only covers rows where pid is set.
CREATE INDEX IF NOT EXISTS idx_metrics_pid_time
    ON metrics (pid, time DESC)
    WHERE pid IS NOT NULL;

-- =============================================================================
-- Continuous aggregate — 5-minute downsampling
-- =============================================================================
-- Keeps the raw hypertable lean while allowing fast historical queries over
-- longer time ranges. Refreshed automatically by TimescaleDB background jobs.

CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time)  AS bucket,
    host_id,
    metric_type,
    pid,
    process_name,
    avg(value)                      AS avg_value,
    max(value)                      AS max_value,
    min(value)                      AS min_value
FROM metrics
GROUP BY bucket, host_id, metric_type, pid, process_name
WITH NO DATA;   -- populate lazily; background job fills it in

-- Refresh policy: keep the aggregate up to date as new data arrives.
-- Refreshes any bucket that is between 10 minutes and 1 hour old.
SELECT add_continuous_aggregate_policy(
    'metrics_5min',
    start_offset => INTERVAL '1 hour',
    end_offset   => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);

-- =============================================================================
-- Retention policies
-- =============================================================================

-- Raw metrics: keep 30 days, then drop automatically.
SELECT add_retention_policy(
    'metrics',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

-- The continuous aggregate is not given a retention policy here — it will be
-- retained indefinitely by default. Add one in Phase 4+ once you have real
-- numbers for how large metrics_5min grows (target: ~180 days).

-- =============================================================================
-- SQLite is used for config/alert data (see infra/db/init_sqlite.py).
-- The tables below are the TimescaleDB-side anomaly log only.
-- =============================================================================

CREATE TABLE IF NOT EXISTS anomalies (
    id              BIGSERIAL        PRIMARY KEY,
    detected_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    host_id         TEXT             NOT NULL DEFAULT 'local',
    metric_type     TEXT             NOT NULL,
    pid             INTEGER,
    process_name    TEXT,
    observed_value  DOUBLE PRECISION NOT NULL,
    baseline_mean   DOUBLE PRECISION NOT NULL,
    baseline_stddev DOUBLE PRECISION NOT NULL,
    z_score         DOUBLE PRECISION NOT NULL,
    resolved        BOOLEAN          NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_anomalies_host_time
    ON anomalies (host_id, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomalies_unresolved
    ON anomalies (resolved, detected_at DESC)
    WHERE resolved = FALSE;