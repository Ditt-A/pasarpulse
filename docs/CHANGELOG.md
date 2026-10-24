# Changelog

## v6.1
- Restored the missing PIHPS province × commodity × market-level daily input as the default price source.
- Added retained monthly raw snapshots, checksums, unit/source-version/revision metadata, and explicit province mapping coverage.
- Added fixed rolling-origin price-only baselines for eligible series.
- Made Parquet output optional when a runtime has no `pyarrow`/`fastparquet`; CSV remains available.

## v6
- Replaced manual PIHPS/Bapanas dependency with public SP2KP downloader/parser.
- Added BIG province-boundary downloader and province-fallback satellite-zone builder.
- Populated complete 2023–2026 calendar events.
- Populated historical/current official HAP thresholds.
- Integrated references and SP2KP stages into notebook and orchestration.
