# Polymarket Wallet Tracker

Week01 project skeleton for a read-only Polymarket wallet research system.

## Layout

- `backend/`: FastAPI service, configuration, API probe, collector primitives.
- `frontend/`: Next.js dashboard placeholder.
- `infra/`: local Docker Compose for Postgres, Redis, and backend.
- `docs/`: ADRs, data dictionary, API probe report, and sanitized samples.

## Local backend

```bash
cd codes
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,probe]"
uvicorn backend.app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Run the read-only API probe:

```bash
python -m backend.scripts.api_probe --output-dir docs/samples
```

The probe writes sanitized JSON samples and a structured run summary. It does not
use private keys, cookies, signing credentials, or order endpoints.

## Market data ingestion

Apply the PostgreSQL schema and run a bounded read-only market ingestion:

```bash
python -m backend.scripts.db_migrate
python -m backend.scripts.ingest_market_data --max-markets 500
```

For a smoke test, keep the run small:

```bash
python -m backend.scripts.ingest_market_data --max-markets 5 --page-limit 5 --holders-market-limit 2 --holders-limit 3
```
