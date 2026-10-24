# PasarPulse deployment

PasarPulse is an offline-first national food-price early-warning intelligence
platform. The browser is a Next.js application; the API is FastAPI; both load
the prepared `demo_data/` snapshot. Runtime never trains a model and does not
call PIHPS, BPS, weather, satellite, or map-tile APIs.

## Local development

```bash
python -m venv .venv-pasarpulse
. .venv-pasarpulse/bin/activate
pip install -r requirements-demo.txt
PYTHONPATH=. uvicorn app.backend.main:app --reload --port 8000
```

In another terminal:

```bash
cd app/frontend
npm install
PASARPULSE_INTERNAL_API_URL=http://localhost:8000 npm run dev
```

Open <http://localhost:3000>. The API OpenAPI page is at
<http://localhost:8000/docs>.

The browser uses the same-origin `/api` path. Next.js proxies it to FastAPI,
so opening the dashboard through a WireGuard address does not make the browser
try to reach its own `localhost:8000`. Docker defaults to the internal service
name `http://backend:8000`; the local development command above points the
Next.js proxy at a host-run FastAPI process.

The Docker backend uses the smaller `requirements-runtime.txt`; PyArrow,
DuckDB, and pytest remain available in `requirements-demo.txt` for local
artifact work and tests but are not needed by the replay-serving process.

## Docker

```bash
docker compose up --build
```

Open <http://localhost:3000>. The only optional secret is
`PASARPULSE_LLM_API_KEY`; pass it through the shell or a local untracked `.env`
file. Never put it in a Dockerfile, source file, notebook, or GitHub Actions
variable committed to the repository.

Without the key, the complete product remains usable but Copilot returns an
explicit configuration error; no canned answer is generated. When configured,
the backend sends only structured forecast/evidence context to
`gemini-3.5-flash-lite`, requests high thinking, requires JSON output, and
validates the returned numbers, evidence IDs, and dashboard actions before
showing it. Provider failures and validation failures are surfaced as errors,
not replaced with an answer.

## Rebuilding artifacts

The committed replay snapshot is built from the validated multimodal OOF
artifact. It selects the 7-day all-modality/dynamic-graph winner and the
14-day price/calendar winner, while keeping other modalities available as
explicit context-only evidence for the 14-day contract:

```bash
PYTHONPATH=. python scripts/build_multimodal_replay_snapshot.py
PYTHONPATH=. python scripts/validate_demo_artifacts.py
```

The source is `results/multimodal_ablation/oof_predictions.csv`, with
forecast-time context from `results/multimodal_ablation/replay_context.csv`.
Later realized `target_price` values are retained only for the replay reveal
and evaluation; the builder and API recompute warnings from `current_price` and
`predicted_price` only.

## Environment variables

See [.env.example](.env.example). Useful paths are
`PASARPULSE_FORECAST_PATH`, `PASARPULSE_EVIDENCE_PATH`,
`PASARPULSE_GEOGRAPHY_PATH`, and `PASARPULSE_MODE=auto|historical_replay|inference_snapshot|benchmark_only`.

## Deployment architecture

See [docs/DEPLOYMENT_ARCHITECTURE.md](docs/DEPLOYMENT_ARCHITECTURE.md),
[docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md), and
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
