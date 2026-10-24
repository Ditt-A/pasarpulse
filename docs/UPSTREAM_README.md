# PasarPulse-MM Data Pipeline v6

Pipeline modular untuk membangun dataset model-ready dari **sumber publik tanpa request access**. Harga anchor default menggunakan PIHPS Bank Indonesia pada level provinsi-komoditas-market-level-harian; SP2KP tetap tersedia sebagai retail benchmark/fallback. Weather, produksi tahunan, Sentinel-2, kalender, dan graph dipertahankan sebagai modalitas terpisah dengan mask dan freshness.

## Yang sudah disertakan

- `data/manual/calendar_events.csv`: kalender resmi 2023–2026, termasuk perubahan cuti bersama 2023, tambahan 18 Agustus 2025, dan awal Ramadan hasil Sidang Isbat.
- `data/manual/official_thresholds.csv`: HAP upper/lower untuk BM, CRM, CMK dari Perbadan 11/2022 sampai Perbadan 12/2024.
- `tools/reference.py`: downloader polygon provinsi BIG + pembuat province-fallback `satellite_zones.geojson`.
- `tools/sp2kp.py`: discovery resource data.go.id/CKAN, downloader bulanan, duplicate-month selection, flexible Excel/CSV parser, dan canonicalization.
- `tools/pihps.py`: downloader report PIHPS per komoditas/market-level, raw JSON snapshot + SHA-256 manifest, unit/revision metadata, and province mapping audit.
- `tools/baselines.py`: fixed leakage-safe last-price and seasonal-lag rolling-origin baselines for eligible series.
- `main_data_pipeline.ipynb`: seluruh tahap sudah terhubung.

## First run di VM AI Centre

```bash
pip install -r requirements.txt
python prepare_public_inputs.py
```

Atau buka `main_data_pipeline.ipynb` dan jalankan dari atas ke bawah. Stage references akan membuat:

```text
data/reference/indonesia_provinces.geojson
data/reference/satellite_zones.geojson
```

Stage PIHPS akan membuat:

```text
data/raw/pihps/pihps_<market>_<commodity>_YYYY_MM.json
data/processed/pihps_snapshot_manifest.csv
data/processed/pihps_revision_audit.csv
data/processed/pihps_mapping_audit.csv
data/processed/price_daily.csv
data/processed/price_coverage_audit.csv
reports/tables/price_only_baseline_metrics.csv
```

The raw PIHPS files are the retained source snapshots. Each canonical row carries
`price_unit`, `extraction_timestamp`, `source_version`, and `revision_flag`;
revisions are audited through the snapshot manifest rather than overwritten in
place. The current public PIHPS table returns 34 provinces. The mapping audit
explicitly records the four expected Papua expansion provinces that are not
returned by that source, and those series remain ineligible rather than being
imputed.

## Sumber publik yang dipakai

- SP2KP/Data.go.id: https://data.go.id/dataset/dataset/tingkat-harga-daerah
- PIHPS/Bank Indonesia report page: https://www.bi.go.id/hargapangan/TabelHarga/PedagangBesarKomoditas
- BIG province layer: https://geoservices.big.go.id/rbi/rest/services/BATASWILAYAH/BATAS_WILAYAH/MapServer/12
- Calendar SKB: Kementerian PANRB/Kemenko PMK links di `calendar_events.csv`
- Ramadan starts: Kementerian Agama links di `calendar_events.csv`
- HAP: BPK regulation links di `official_thresholds.csv`

## Catatan parser harga

PIHPS report responses are downloaded month by month for Bawang Merah, Cabai
Merah Keriting, and Cabai Rawit Merah at traditional retail, wholesale, and
producer levels. The endpoint returns Indonesian thousands-formatted values
(for example `40,800`), which are normalized to `40800` IDR/kg. National totals
and non-province rows are excluded from the province panel but retained in the
mapping audit.

SP2KP remains available when `prices.source: sp2kp` is selected. Its parser
supports three layouts:

Portal pernah menampilkan resource ganda untuk bulan yang sama. Kode memilih resource dengan metadata terbaru lalu ukuran terbesar. Parser mendukung tiga layout umum:

1. long: tanggal–provinsi–komoditas–harga;
2. wide commodity: tanggal–provinsi + kolom komoditas;
3. wide day: provinsi–komoditas + kolom tanggal 1–31.

Jika format portal berubah, cek `data/processed/sp2kp_resource_manifest.csv`, khususnya kolom `parse_status`, lalu simpan contoh file yang gagal untuk menambah adapter.

Price-only baselines are evaluated after the eligibility audit with a fixed
rolling-origin protocol (`min_train_days: 365`), without tuning on future labels.

## Credentials

`setup_credentials.py` milikmu tetap ditaruh di project root untuk ERA5 dan Sentinel-2. File berisi secret tidak dimasukkan ke ZIP. BPS, SP2KP, BIG, calendar, dan thresholds tidak memerlukan token.

## Default aman

ERA5 dan Sentinel download tetap `false` di `config.yaml` agar first run tidak langsung menghabiskan storage. Setelah public price + reference pipeline sukses, aktifkan bertahap.
