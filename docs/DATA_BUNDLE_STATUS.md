# PasarPulse data bundle status

Price target period: **2024-02-01 through 2026-07-31**. Context acquisition
starts on **2024-01-01** so lagged weather and satellite observations can be
constructed without borrowing future information.

## Included now

- The complete PasarPulse-MM v6 pipeline.
- PIHPS daily report snapshots for 2024-02-01 through 2026-07-31 across the three target commodities and three market levels.
- PIHPS snapshot, checksum, unit/revision, and province-mapping audits.
- Price-only rolling-origin baseline predictions and metrics for eligible series.
- Official calendar-event input table.
- Official price-threshold input table.
- Generated daily calendar features for the target period.
- A deterministic manifest for all **30 expected SP2KP monthly workbooks**.
- BPS source/year manifest for production and harvested area (2023–2025).
- Downloaded and validated BIG province boundaries and province-fallback satellite zones (38 features each).
- Downloaded BPS production and harvested-area source snapshots for 2023–2025, with raw HTML, selected CSV tables, merged panel, and acquisition manifest.
- ERA5-Land hourly temperature, precipitation, soil-water, and solar-radiation acquisition plus area-weighted province-day aggregation.
- Sentinel-2 Collection 1 L2A COG discovery and bounded regional extraction of NDVI, EVI, and NDWI with SCL masking.
- A checksum-verified, dated 2026-01-01 Geofabrik Indonesia snapshot for candidate road/ferry/port/market connectivity.
- Rolling 90-day model-inferred price-dependence edges, built separately for commodity and market level.
- The official Kemendag/BIG market layer: 625 market points, 610 parseable operating-frequency declarations, and a 38-province summary with one explicit source gap for DKI Jakarta.
- A resumable one-command acquisition script and machine-readable status/checksum files.

The final ERA5-Land aggregate is **35,834 rows** (38 provinces × 943 days,
2024-01-01 through 2026-07-31), with complete province-day coverage and no
duplicate keys. The June 2026 CDS response arrived as two aligned NetCDF
members inside a ZIP; the pipeline preserves the original payload hash and
normalizes the members into one canonical dataset before aggregation.

## Availability caveats

The BPS panel contains 342 province × commodity × year rows across 2023–2025.
336 rows have both production and harvested-area values. Six source cells are
absent in the official tables and remain explicit `NaN` values rather than being
fabricated: Bali/Cabai Keriting (2023), Papua Pegunungan/Cabai Keriting (2023),
Kalimantan Utara/Bawang Merah (2024), and all three commodities for Papua
Pegunungan (2024).

`satellite_zones.geojson` is a province-level fallback. Scene discovery uses a
fixed interior representative point and one locked MGRS grid for each province
so that temporal changes do not jump between arbitrary islands or tiles;
extraction is clipped to the province overlap. Sentinel-derived values are therefore labelled as
regional vegetation proxies, not parcel-level crop measurements or commodity
production estimates.

The final Sentinel manifest contains 786 scenes across all 38 provinces. Every
scene produced usable NDVI/EVI/NDWI values; 781 pass the normal valid-pixel
quality rule and five are retained with an explicit `low_valid_pixels` flag.
No province switches MGRS grids across the archived series.

The OSM and rolling-price graphs are not shipment data. Their edge
interpretations are fixed to `candidate_structural_connectivity` and
`model_inferred_price_dependence`, respectively. They do not provide a
propagation probability.

The dated OSM extraction yields 38 province summaries, 5,921 infrastructure
points, and 70 candidate inter-province transport edges. The combined static
candidate graph contains 73 edges; the rolling price-dependence table contains
37,485 commodity-market-snapshot edges.

The BIG/Kemendag market service contains no DKI Jakarta point. DKI remains in
the province summary as `no_points_in_source`; it is not assigned a fabricated
zero. Operating-day text that specifies only opening hours is also left
unparsed.

ERA5-Land accumulations use the next-day 00:00 UTC value for the previous UTC
day. Segment-boundary files contribute only precipitation and radiation;
their single 00:00 record is explicitly excluded from daily temperature and
soil-moisture statistics. Context is replay-gated with a five-day publication
lag. Sentinel scenes
use STAC `created`/`updated` timestamps where available, and vegetation
anomalies use only earlier scenes in the same zone and calendar month.
The stored Copernicus Data Space S3 key failed preflight with
`InvalidAccessKeyId`, so Sentinel acquisition uses the public Earth Search /
AWS Open Data COG mirror and records that fallback explicitly.

Run this on the A100 or another Linux host with the research dependencies and
the private `setup_credentials.py` file available locally:

```bash
python -m pip install -r requirements-research.txt
python pipeline/verify_multimodal_access.py --source cds
python pipeline/verify_multimodal_access.py --source earth-search
python pipeline/acquire_all_data.py --include-multimodal
python pipeline/validate_multimodal_artifacts.py
```

The downloader is resumable and writes:

- `data/acquisition/download_status.csv`
- `data/acquisition/download_status.json`
- `data/acquisition/SHA256SUMS.txt`

Large raw ERA5 NetCDF files and the 1.69 GB OSM PBF stay on the acquisition
host and are excluded from Git. Versioned manifests, hashes, normalized
Parquet/CSV artifacts, graph tables, and validation outputs are the portable
research contract. The completed A100 ablation outputs are stored under
`results/multimodal_ablation/`; they contain all 14 chronological folds and a
25-check result-level validation report.
