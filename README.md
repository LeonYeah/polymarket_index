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
