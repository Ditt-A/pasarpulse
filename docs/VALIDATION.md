# Validation status

The package was checked with:

- Python syntax compilation for all modules and scripts;
- notebook JSON and code-cell syntax validation;
- synthetic SP2KP tests for long, wide-commodity, wide-day, sheet-inferred, and ZIP layouts;
- calendar feature tests around Ramadan and Idulfitri;
- historical/current HAP effective-date merge tests;
- BIG-style GeoJSON validation and province-fallback zone generation;
- synthetic end-to-end merge, graph, QA, and five diagnostic figures.
- synthetic PIHPS response parsing, Indonesian thousands-format price parsing, and rolling-origin baseline scoring.
- live PIHPS acquisition for 2024-02-01 through 2026-07-31: 270 monthly snapshots, 181,177 canonical observations, 34 returned provinces, and 279 eligible series.

PIHPS live acquisition has been executed and is resumable from `data/raw/pihps/`; the snapshot manifest records each request, response checksum, parsed-row count, and failure status. SP2KP/BIG downloads remain resumable through the existing acquisition path. If Parquet support is unavailable, the pipeline keeps CSV artifacts and continues.
