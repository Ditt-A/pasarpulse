"""Offline smoke tests for public-input parsers.

Run from the project root:
    python tests/test_public_inputs.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pasarpulse.tools.calendar import build_calendar_features
from src.pasarpulse.tools.baselines import run_price_only_baselines
from src.pasarpulse.tools.merge import _merge_thresholds
from src.pasarpulse.tools.pihps import _parse_snapshot
from src.pasarpulse.tools.prices import normalize_price_frame
from src.pasarpulse.tools.reference import _validate_feature_collection, build_satellite_zones
from src.pasarpulse.tools.sp2kp import parse_sp2kp_file


def main() -> None:
    project_root = PROJECT_ROOT
    with tempfile.TemporaryDirectory(prefix="pasarpulse_test_") as temp:
        root = Path(temp)

        raw = pd.DataFrame(
            {
                "date": ["2024-02-01"],
                "province_name": ["Jawa Timur"],
                "commodity_name": ["Cabai Rawit Merah"],
                "market_level": ["eceran"],
                "price_idr_per_kg": ["52.000"],
            }
        )
        normalized = normalize_price_frame(raw, source="SP2KP")
        assert normalized.iloc[0]["province_code"] == "35"
        assert normalized.iloc[0]["commodity_code"] == "CRM"
        assert normalized.iloc[0]["price_idr_per_kg"] == 52000

        pihps = pd.DataFrame(
            {
                "date": ["2026-07-27"],
                "province_name": ["Aceh"],
                "commodity_name": ["Bawang Merah"],
                "market_level": ["retail"],
                "price_idr_per_kg": ["40,800"],
            }
        )
        normalized_pihps = normalize_price_frame(pihps, source="PIHPS")
        assert normalized_pihps.iloc[0]["price_idr_per_kg"] == 40800
        assert normalized_pihps.iloc[0]["price_unit"] == "IDR/kg"

        snapshot, mapping = _parse_snapshot(
            {
                "data": [
                    {"name": "Semua Provinsi", "level": 0, "27/07/2026": "40,000"},
                    {"name": "Aceh", "level": 1, "27/07/2026": "40,800"},
                ]
            },
            commodity_code="BM",
            market_level="retail",
            source_version="PIHPS:test",
            extraction_timestamp="2026-08-04T00:00:00+00:00",
            start_date=pd.Timestamp("2026-07-01"),
            end_date=pd.Timestamp("2026-07-31"),
        )
        assert len(snapshot) == 1
        assert snapshot.iloc[0]["province_code"] == "11"
        assert snapshot.iloc[0]["price_idr_per_kg"] == 40800
        assert any(row["source_province_name"] == "Semua Provinsi" for row in mapping)

        baseline_dates = pd.date_range("2025-01-01", "2026-07-31", freq="D")
        baseline_prices = pd.DataFrame(
            {
                "date": baseline_dates,
                "province_code": "11",
                "province_name": "Aceh",
                "commodity_code": "BM",
                "commodity_name": "Bawang Merah",
                "market_level": "retail",
                "price_idr_per_kg": 40000 + (baseline_dates.dayofweek * 100),
            }
        )
        baseline_audit = pd.DataFrame(
            [{
                "province_code": "11",
                "commodity_code": "BM",
                "market_level": "retail",
                "eligible": True,
            }]
        )
        metrics, _, _ = run_price_only_baselines(
            baseline_prices,
            baseline_audit,
            output_dir=root / "baseline_reports",
            metadata_path=root / "baseline_reports.json",
            start_date="2025-01-01",
            end_date="2026-07-31",
            min_train_days=30,
            save_csv=False,
            save_parquet=False,
        )
        assert set(metrics["model"]) == {"last_price", "seasonal_lag"}
        assert set(metrics["horizon_days"]) == {7, 14}

        workbook = root / "sp2kp.xlsx"
        pd.DataFrame(
            {
                "Tanggal": ["2024-02-01"] * 3,
                "Provinsi": ["Aceh"] * 3,
                "Komoditas": ["Bawang Merah", "Cabai Rawit Merah", "Cabai Merah Keriting"],
                "Harga": [40000, 55000, 50000],
            }
        ).to_excel(workbook, index=False)
        parsed = parse_sp2kp_file(workbook, year=2024, month=2)
        assert set(parsed["commodity_code"].dropna()) == {"BM", "CRM", "CMK"}

        archive = root / "sp2kp.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(workbook, arcname="data/sp2kp.xlsx")
        parsed_zip = parse_sp2kp_file(archive, year=2024, month=2)
        assert len(parsed_zip) == 3

        calendar, _ = build_calendar_features(
            "2024-03-10",
            "2024-04-12",
            events_path=project_root / "data/manual/calendar_events.csv",
            output_base=root / "calendar",
            save_csv=False,
            save_parquet=False,
        )
        assert calendar.loc[calendar["date"].eq(pd.Timestamp("2024-03-12")), "is_ramadan_start"].iloc[0] == 1
        assert calendar.loc[calendar["date"].eq(pd.Timestamp("2024-04-10")), "is_eid_al_fitr"].iloc[0] == 1

        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-09-25", "2024-09-26", "2024-09-27"]),
                "commodity_code": ["BM"] * 3,
                "market_level": ["retail"] * 3,
                "price_idr_per_kg": [42000, 42000, 41000],
            }
        )
        thresholds = pd.read_csv(project_root / "data/manual/official_thresholds.csv")
        merged = _merge_thresholds(panel, thresholds)
        assert list(merged["threshold_exceeded"].astype("Int64")) == [1, 1, 0]
        assert merged.loc[0, "regulation_version"].startswith("Perbadan_11")
        assert merged.loc[1, "regulation_version"] == "Perbadan_12_2024"

        official_codes = [
            "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
            "31", "32", "33", "34", "35", "36", "51", "52", "53", "61",
            "62", "63", "64", "65", "71", "72", "73", "74", "75", "76",
            "81", "82", "91", "92", "94", "95", "96", "97",
        ]
        features = [
            {
                "type": "Feature",
                "properties": {"province_code": code, "province_name": f"P{code}"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                },
            }
            for code in official_codes
        ]
        collection = {"type": "FeatureCollection", "features": features}
        _validate_feature_collection(collection, expected_count=38)
        province_path = root / "provinces.geojson"
        province_path.write_text(json.dumps(collection), encoding="utf-8")
        zones_path = root / "zones.geojson"
        build_satellite_zones(province_path, zones_path)
        zones = json.loads(zones_path.read_text(encoding="utf-8"))
        assert zones["features"][0]["properties"]["zone_method"] == "province_fallback"

    print("All offline public-input smoke tests passed.")


if __name__ == "__main__":
    main()
