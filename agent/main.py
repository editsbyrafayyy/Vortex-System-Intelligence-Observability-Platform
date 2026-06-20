import os
import json
import logging
import uuid
import time

import redis

from collector import collect_snapshot
from .transfrom import flatten_snapshot

logging.basicConfig(
	level = logging.INFO,
	format="%(asctime)s %(levelname)s agent: %(message)s",
)

log = logging.getLogger("agent")

STREAM_NAME = "metrics:ingest"
SCHEMA_VERSION = 1

REDIS_URL = os.environ["AGENT_SECRET"]
HOST_ID = os.environ.get("HOST_ID", "local")
COLLECTOR_INTERVAL = float(os.environ.get("COLLECTOR_INTERVAL", 5))

AGENT_ID = str(uuid.uuid4()) # per process identity

"""Wrap a flat metrics list in the versioned envelope from the doc."""
def build_message(metrics: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "host_id": HOST_ID,
        "agent_id": AGENT_ID,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "auth_secret": AGENT_SECRET,   # checked by the worker, stripped before storage
        "metrics": metrics,
    }

# conenct with redis using a retry loop (tries a total of 10 times)
def connect_redis() -> redis.Redis:
	last_error = None

	for attempt in range(1,11):
		try:
			client = redis.from_url(REDIS_URL, decode_responses = True)
			client.ping()
			log.info("connected to redis at %s", REDIS_URL)
			return client

		except redis.exceptions.ConnectionError as exc:
			last_error = exc
			log.warning("redis not ready (attempt %d/10): %s", attempt, exc)
			time.sleep(2)

	log.error("could not connect to redis after 10 tries: %s", last_error)
	sys.exit(1)

def run(client: redi)


