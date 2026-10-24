# Reference files

Kedua file GeoJSON dibuat otomatis oleh `pipeline.run_references()` atau `python prepare_public_inputs.py`.

- `indonesia_provinces.geojson`: 38 polygon provinsi dari BIG, kolom canonical `province_code` dan `province_name`.
- `satellite_zones.geojson`: salinan polygon provinsi dengan metadata `zone_method=province_fallback`; hanya untuk smoke test.

Untuk eksperimen final, ganti `satellite_zones.geojson` dengan producing-district cropland zones tetapi pertahankan kolom `province_code`, `province_name`, dan geometry EPSG:4326.
