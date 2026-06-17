# Vortex

**Personal System Intelligence & Observability Platform**

A self-hosted, privacy-first monitoring platform for Linux machines. Vortex collects system metrics (CPU, memory, disk, network, processes, Docker containers), stores them in a time-series database, detects anomalies, and surfaces everything through a live web dashboard.

> Built as a portfolio project to demonstrate system design, data structures, and backend engineering — while being genuinely useful as a daily-use tool.

---

## Features

- **System metrics** — CPU, memory, disk I/O, and network stats read directly from `/proc`
- **Process monitoring** — per-process CPU/memory usage with PID attribution and network connection tracking
- **Docker container stats** — CPU, memory limit vs. usage, and network I/O per container via the Docker SDK
- **Time-series storage** — TimescaleDB hypertable with time-based partitioning, continuous aggregates, and automated retention policies
- **Anomaly detection** — rolling z-score baseline per metric/process, with a min-heap for efficient top-N tracking
- **Live dashboard** — server-rendered HTMX + Jinja2 dashboard with real-time partial updates, no JS framework required
- **REST API** — FastAPI backend with full OpenAPI docs, Pydantic v2 schemas, and a Prometheus `/metrics` endpoint
- **Multi-machine support** *(v1.1)* — agent/server architecture with JWT auth and Redis Streams transport
- **Natural-language queries** *(v1.2, optional)* — plain-English questions translated to TimescaleDB SQL via Claude API

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Arch Machine(s)                      │
│                                                             │
│  ┌──────────────┐         ┌──────────────────────────────┐  │
│  │    Agent     │         │        Central Server        │  │
│  │  (psutil +   │────────▶│                              │  │
│  │  docker SDK) │  Redis  │  FastAPI + Pydantic          │  │
│  │              │ Streams │  JWT Auth                    │  │
│  │  Collects:   │         │  Nginx (reverse proxy)       │  │
│  │  - CPU/RAM   │         │                              │  │
│  │  - Disk/Net  │         │  ┌────────────┐              │  │
│  │  - Processes │         │  │ TimescaleDB│              │  │
│  │  - Containers│         │  │ (Postgres) │              │  │
│  └──────────────┘         │  └────────────┘              │  │
│                           │  ┌────────────┐              │  │
│                           │  │   Redis    │              │  │
│                           │  │  (cache +  │              │  │
│                           │  │  streams)  │              │  │
│                           │  └────────────┘              │  │
│                           └──────────────────────────────┘  │
│                                      │                      │
│                            ┌─────────▼──────────┐           │
│                            │     Dashboard      │           │
│                            │  HTMX + Jinja2     │           │
│                            └────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

In v0.1–v1.0, agent and server run on the same machine. The agent/server split is introduced in v1.1.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| API | FastAPI + Pydantic v2 |
| Primary DB | PostgreSQL + TimescaleDB |
| Local config | SQLite |
| Cache + transport | Redis (TTL cache + Streams) |
| Metrics collection | psutil + Docker SDK |
| Auth | JWT via python-jose + bcrypt |
| Testing | pytest, pytest-asyncio, httpx |
| Orchestration | Docker + Docker Compose |
| Reverse proxy | Nginx |
| Dashboard | Jinja2 + HTMX |
| Logging | structlog (JSON) |

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Linux (reads from `/proc` — Arch recommended, any distro works)

### Run

```bash
git clone https://github.com/your-username/vortex.git
cd vortex
cp .env.example .env        # fill in secrets
docker compose up
```

The dashboard is available at `http://localhost:8000`.  
API docs (auto-generated) are at `http://localhost:8000/docs`.

### Environment variables

See `.env.example` for all required variables. At minimum:

```
POSTGRES_PASSWORD=...
REDIS_URL=redis://redis:6379
JWT_SECRET=...
```

---

## API

```
GET  /api/v1/snapshot                  # current CPU/mem/disk/net summary
GET  /api/v1/metrics/{metric_type}     # historical query (start, end, bucket, host_id)
GET  /api/v1/processes                 # process list with resource usage
GET  /api/v1/processes/{pid}/history   # historical metrics for a single PID
GET  /api/v1/network/connections       # connections with process attribution
GET  /api/v1/docker/containers         # container stats
GET  /api/v1/anomalies                 # anomaly log (filterable)
GET  /metrics                          # Prometheus exposition format
```

Full interactive docs at `/docs` when running.

---

## Project Structure

```
vortex/
├── collector/       # psutil//proc readers, Docker SDK, ring buffer
├── api/             # FastAPI app, routers, Pydantic schemas
├── detection/       # anomaly detection (sliding window, min-heap)
├── dashboard/       # Jinja2 templates, HTMX views, static assets
├── agent/           # agent-mode wrapper, JWT client (v1.1)
├── ai/              # NL-to-SQL tool-use integration (v1.2, optional)
├── docs/
│   └── decisions/   # Architecture Decision Records (ADRs)
├── tests/
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Data Structures

A core goal of this project is making data structure choices explicit and visible to reviewers.

| Structure | Where used | Why |
|---|---|---|
| Ring buffer | Collector in-memory buffer | Fixed memory footprint, O(1) insert, natural "last N samples" semantics |
| Min-heap | Anomaly detector top-N tracking | Maintain top-N anomalous processes without sorting the full list each cycle |
| Hash map | PID → process metadata index | O(1) lookup when correlating metrics, connections, and anomalies by PID |
| Graph | Network connection model | Natural representation of process → socket → remote IP relationships |

Each is implemented from scratch with complexity trade-offs noted in code comments.

---

## Releases

| Version | Phases | Status |
|---|---|---|
| v0.1 | Collector + TimescaleDB pipeline | In progress |
| v0.2 | FastAPI layer + pytest coverage | Planned |
| v0.3 | Anomaly detection + dashboard | Planned |
| v1.0 | Full Docker Compose stack + container monitoring | Planned |
| v1.1 | Agent/server mode + JWT auth | Planned |
| v1.2 | NL-to-SQL query interface (optional) | Planned |

---

## Architecture Decision Records

Design trade-offs are documented in [`docs/decisions/`](docs/decisions/) as lightweight ADRs:

- **ADR-1** — Polling interval vs. observer effect
- **ADR-2** — Push vs. pull metrics
- **ADR-3** — Retention and downsampling strategy
- **ADR-4** — Statistical vs. threshold-based anomaly detection
- **ADR-5** — JWT vs. session-based auth for agents
- **ADR-6** — Redis Streams vs. Kafka

---

## License

MIT
