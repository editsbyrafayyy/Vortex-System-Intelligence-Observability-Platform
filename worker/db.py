"""
Database layer for the worker.

Two databases:
  - TimescaleDB (asyncpg)  — metric time-series storage
  - SQLite (stdlib)        — config/alert rules/api_keys (no container needed,
                             just a file on disk mounted via docker volume)
"""

import logging
import os
import sqlite3  # sqlite is a file based database and doesn't require a docker container, we use this for api_keys, alert_rules and anomalies
# as postrgres would be an overkill for such low-volume low-write operations
import asyncpg  # this is a postegres driver that allows for communication with postgres wire protocol
# Our worker program is an async program it needs to handle multiple messages at a time, if it were an sync program, every database call would block
# the complete event loop (no other message from the loop could be processed while waiting for postgres to respond). the library provides the control back
# to the event loop during the wait so it can continue.

from agent.schemas import MetricPayload  # the MetricPayload function is a pydantic model, it ensures that before the data reaches the DB it has been validated
# this ensures that the DB layer doesn't have to perform any parsing/checking. We don't want the DB to throw a low-level exception if it gets malformed data, so
# to avoid that we use a pydantic model that parses the data and makes it easier on the DB (a major point of performance bottleneck as it has limited resources)

log = logging.getLogger(__name__)  # this helps with debugging as each log line is tagged with which file it is from

SQLITE_PATH = os.getenv("SQLITE_PATH", "/app/vortex.db")  # allows us to read the env file directly instead of having to hardcodde it

# =============================================================================
# TimescaleDB
# =============================================================================


''' The idea here ist that opening a DB connection is expensive (requires a complete TCP handshake) so we always want to minimize the times a new connection needs to
created with the DB, what a connection pool does is that once a function is done using the connection instead of closing the conenction, it returns it back to
the pool so a new message can make use of it without having to create a new connection with the DB'''
async def create_timescale_pool(dsn: str) -> asyncpg.Pool:
    """
    Create a connection pool to TimescaleDB.
    Data Source Name is a connection string in the format
    DSN format: postgresql://user:password@host:port/dbname
    we keep a min of 2 connections open at all times even when idle
    """
    return await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)


async def write_metrics(pool: asyncpg.Pool, payload: MetricPayload) -> int:
    """
    Batch-insert all samples from one agent payload into the metrics hypertable, this saves us DB round-trip cost.
    Uses executemany — single round-trip per batch regardless of sample count.
    Returns the number of rows inserted.
    """
    rows = [
        (
            payload.collected_at,    # time        TIMESTAMPTZ
            payload.host_id,         # host_id     TEXT
            sample.metric_type,      # metric_type TEXT
            sample.pid,              # pid         INTEGER  (nullable)
            sample.process_name,     # process_name TEXT    (nullable)
            sample.value,            # value       DOUBLE PRECISION
            sample.unit,             # unit        TEXT
            sample.metadata,         # metadata    JSONB
        )
        for sample in payload.metrics
    ]

    sql = """
        INSERT INTO metrics
            (time, host_id, metric_type, pid,
            process_name,value, unit, metadata)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7, $8)  # these are placeholders that asyncpg subs values into from the tuple (SQL Injection Prevention and Prepared statement use)
    """

    async with pool.acquire() as conn:
        await conn.executemany(sql, rows)

    log.debug(
        "wrote %d rows | host=%s agent=%s",
        len(rows), payload.host_id, payload.agent_id,
    )
    return len(rows)


# =============================================================================
# SQLite
# =============================================================================

# We are using sqlite for data that is rarely written but read occasionally 
def init_sqlite() -> sqlite3.Connection:
    """
    Open (or create) the SQLite database and ensure all tables exist.
    Safe to call on every startup — all statements are IF NOT EXISTS.
    The file is created at SQLITE_PATH if it doesn't exist yet.
    """
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row   # dict-like row access
    conn.execute("PRAGMA journal_mode=WAL")  # safer concurrent reads

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id           INTEGER  PRIMARY KEY,
            key_hash     TEXT     NOT NULL,      -- bcrypt hash; never store
            label        TEXT     NOT NULL,      -- e.g. 'dashboard'
            created_at   TEXT     NOT NULL,      -- ISO-8601
            last_used_at TEXT,
            revoked      INTEGER  NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS alert_rules (
            id                INTEGER PRIMARY KEY,
            metric_type       TEXT    NOT NULL,
            target            TEXT,  -- process name, or NULL for system-wide
            z_score_threshold REAL    NOT NULL DEFAULT 3.0,
            window_minutes    INTEGER NOT NULL DEFAULT 60,
            enabled           INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS anomalies (
            id              INTEGER PRIMARY KEY,
            detected_at     TEXT    NOT NULL,    -- ISO-8601
            host_id         TEXT    NOT NULL DEFAULT 'local',
            metric_type     TEXT    NOT NULL,
            pid             INTEGER,
            process_name    TEXT,
            observed_value  REAL    NOT NULL,
            baseline_mean   REAL    NOT NULL,
            baseline_stddev REAL    NOT NULL,
            z_score         REAL    NOT NULL,
            resolved        INTEGER NOT NULL DEFAULT 0
        );
    """)

    conn.commit()
    log.info("sqlite ready at %s", SQLITE_PATH)
    return conn
