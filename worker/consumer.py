"""
Worker: Redis Streams consumer for the metrics:ingest stream.

Flow per message:
  1. XREADGROUP   — claim next undelivered message
  2. Auth check   — validate AGENT_SECRET, strip it before Pydantic sees the payload
  3. Parse JSON   — decode the raw bytes from the 'payload' field
  4. Validate     — Pydantic MetricPayload
  5. DB write     — batch-insert into TimescaleDB via asyncpg
  6. XACK         — acknowledge so Redis drops it from the pending-entries list

Crash/restart recovery:
  On startup the worker drains any pending (unacked) messages from a previous
  crashed run via XAUTOCLAIM before entering the normal loop.
"""

import asyncio  # a single threat that switches between tasks whenever one is waiting on I/O (redis read. DB write), without this threads/processes to handle concurrent
# I/O would be needed, this gives cooperative concurrency in a single thread (lighter and easier to reason about for I/O heavy workloads)
import json 
import logging
import os
import signal  # allows the workder to respond to OS signals (SIGTERM - docker stop sends this) and SIGNIT (Ctrl + C command), without this docker stop gives
# up the container within 10 seconds, and any messages in the redis stream being written would be lost mid-insert.

import redis.asyncio as aioredis  # this is the offical redis python client, but this works asynchronously, the agent was using the sync varient for reference.
from pydantic import ValidationError

from agent.schemas import MetricPayload
from worker.db import create_timescale_pool, init_sqlite, write_metrics

log = logging.getLogger(__name__)

# These are all module level constraints, 
STREAM_NAME = "metrics:ingest"
GROUP_NAME = "vortex-workers"
CONSUMER_ID = os.getenv("WORKER_ID", "worker-1")
BLOCK_MS = 2_000   # how long XREADGROUP blocks waiting for new messages (2 seconds)
BATCH_SIZE = 50  # max messages claimed per read, issue is that if the worker crashes mid batch, all the messages go back to pending.
CLAIM_IDLE_MS = 30_000  # ms a message must be pending bfr XAUTOCLAIM reclaim

AGENT_SECRET = os.environ["AGENT_SECRET"]   # must match agent's env var, if not the worker crashes right away as that would be security issue (no auth validation)

''' A redis stream is just a log but it contains bookmarks to ensure that the reader only sees the messages that have not been read. The consumer group gives the
stream a bookmark per group, so redis tracks all the messsages that have been delivered and which have only been ack-ed, only the messages that have not beem
delivered are sent to the consumer group '''

#   
async def ensure_consumer_group(r: aioredis.Redis) -> None:
    """
    Create the consumer group if it doesn't already exist.
    MKSTREAM ensures the stream key exists even before
    the agent pushes anything.
    '$' = start delivering only new messages on first run.
    """
    try:
        await r.xgroup_create(STREAM_NAME, GROUP_NAME, id="$", mkstream=True)
        log.info("consumer group '%s' created on '%s'", GROUP_NAME, STREAM_NAME)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            log.debug("consumer group already exists — skipping create")
        else:
            raise


# =============================================================================
# Startup: drain pending messages from a previous crashed run
# =============================================================================

async def drain_pending(r: aioredis.Redis, pool) -> None:
    """
    Reclaim and process messages that were delivered to a now-dead consumer
    but never acknowledged. Runs once at startup via XAUTOCLAIM (Redis 7+).
    """
    cursor = "0-0"
    reclaimed = 0

    while True:
        next_cursor, messages, _ = await r.xautoclaim(
            STREAM_NAME, GROUP_NAME, CONSUMER_ID,
            min_idle_time=CLAIM_IDLE_MS,
            start_id=cursor,
            count=BATCH_SIZE,
        )
        for msg_id, fields in messages:
            await _handle_message(r, pool, msg_id, fields)
            reclaimed += 1

        if next_cursor in (b"0-0", "0-0"):
            break
        cursor = next_cursor

    if reclaimed:
        log.info("reclaimed %d pending messages on startup", reclaimed)


# =============================================================================
# Message handler
# =============================================================================

async def _handle_message(
    r: aioredis.Redis,
    pool,
    msg_id: bytes,
    fields: dict,
) -> None:
    """
    Parse → auth check → validate → write → ack a single stream message.

    Ack policy:
      - Bad JSON, auth failure, schema error → log + ack
      (poison-pill protection)
      - DB write failure → log, do NOT ack (stays pending for retry)
    """

    # --- extract raw payload -------------------------------------------------
    # The agent stores the JSON string under the key "payload"
    raw = fields.get(b"payload") or fields.get("payload")

    if raw is None:
        log.warning("msg %s missing 'payload' field — discarding", msg_id)
        await r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    # --- parse JSON ----------------------------------------------------------
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("msg %s invalid JSON: %s — discarding", msg_id, exc)
        await r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    # --- auth check ----------------------------------------------------------
    # The agent embeds auth_secret in the envelope. Validate it here, then
    # remove it so MetricPayload (which doesn't have that field)
    incoming_secret = data.pop("auth_secret", None)
    if incoming_secret != AGENT_SECRET:
        log.warning("msg %s failed auth — discarding", msg_id)
        await r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    # --- schema version guard ------------------------------------------------
    if data.get("schema_version") != 1:
        log.warning(
            "msg %s unknown schema_version=%s — discarding",
            msg_id, data.get("schema_version"),
        )
        await r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    # --- Pydantic validation -------------------------------------------------
    try:
        payload = MetricPayload.model_validate(data)
    except ValidationError as exc:
        log.error("msg %s schema validation failed: %s — discarding", msg_id, exc)
        await r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    # --- write to TimescaleDB ------------------------------------------------
    try:
        rows = await write_metrics(pool, payload)
        log.info(
            "ingested %d rows | host=%s agent=%s msg=%s",
            rows, payload.host_id, payload.agent_id, msg_id,
        )
    except Exception as exc:
        # Do NOT ack — leave pending so it retries after CLAIM_IDLE_MS
        log.error("DB write failed for msg %s: %s", msg_id, exc)
        return

    # --- acknowledge ---------------------------------------------------------
    await r.xack(STREAM_NAME, GROUP_NAME, msg_id)


# =============================================================================
# Main consume loop
# =============================================================================

async def consume_loop(r: aioredis.Redis, pool) -> None:
    log.info(
        "worker '%s' listening on '%s' (group '%s')",
        CONSUMER_ID, STREAM_NAME, GROUP_NAME,
    )
    while True:
        results = await r.xreadgroup(
            groupname=GROUP_NAME,
            consumername=CONSUMER_ID,
            streams={STREAM_NAME: ">"},   # '>' = undelivered messages only
            count=BATCH_SIZE,
            block=BLOCK_MS,
        )
        if not results:
            continue   # timeout, no new messages — loop and block again

        for _stream, messages in results:
            for msg_id, fields in messages:
                await _handle_message(r, pool, msg_id, fields)


# =============================================================================
# Entrypoint
# =============================================================================

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    redis_url = os.environ["REDIS_URL"]
    timescale_dsn = os.environ["TIMESCALE_DSN"]

    r = await aioredis.from_url(redis_url, decode_responses=False)
    pool = await create_timescale_pool(timescale_dsn)

    init_sqlite()   # creates /app/vortex.db + tables if they don't exist yet

    await ensure_consumer_group(r)
    await drain_pending(r, pool)

    # graceful shutdown on SIGTERM / SIGINT (docker stop sends SIGTERM)
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)

    consumer_task = asyncio.create_task(consume_loop(r, pool))
    await stop

    log.info("shutdown signal — stopping worker")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await r.aclose()
    await pool.close()
    log.info("worker stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
