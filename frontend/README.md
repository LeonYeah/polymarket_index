# Frontend

Next.js dashboard for Week07 API, wallet detail, market detail, watchlist, and alert review.

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The frontend reads only the local FastAPI backend. It does not call Polymarket APIs directly.
Alert queries are read-only. Run rules explicitly with `POST /alerts/generate` or the backend CLI.
