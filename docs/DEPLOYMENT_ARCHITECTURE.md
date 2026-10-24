# Deployment architecture

```text
Browser / Next.js
  ├── MapLibre province map
  ├── ECharts forecast/evidence views
  ├── alert work queue
  └── PasarPulse Copilot panel
              │ HTTP JSON
              ▼
FastAPI / read-only artifact API
  ├── snapshot repository (CSV/JSON/GeoJSON)
  ├── warning and leakage guards
  ├── benchmark loader
  └── Gemini reasoning with explicit error states
```

Training stays offline in the research workspace. Docker includes only the
prepared product snapshot, compact benchmark CSVs, and application code. It
does not include notebooks, raw satellite files, training caches, or the fitted
research weights because the semifinal runtime is a historical replay.

The API can be switched to a prepared inference artifact through environment
configuration, but the current committed product is explicitly Historical
Replay. The absence of a snapshot resolves to Benchmark Only rather than a
synthetic forecast.

The optional Copilot adapter uses the Gemini API model configured by
`PASARPULSE_LLM_MODEL` (default `gemini-3.5-flash-lite`) and keeps the key in
`PASARPULSE_LLM_API_KEY` only. The response must satisfy a JSON schema and then
passes evidence-ID, numerical-fidelity, and dashboard-action validation. Any
failure is surfaced as an explicit Copilot error; no deterministic answer path
is enabled.
