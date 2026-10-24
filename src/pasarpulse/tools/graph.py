"""Static province connectivity, dynamic price dependence, and multilevel graph tools."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod

from ..utils import save_frame

GEOD = Geod(ellps="WGS84")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 0 else np.nan


def build_static_graph(
    provinces_path: str | Path,
    *,
    province_code_col: str,
    province_name_col: str,
    production: pd.DataFrame | str | Path | None,
    output_base: str | Path,
    transport_edges: pd.DataFrame | str | Path | None = None,
    knn: int = 3,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    provinces = gpd.read_file(provinces_path).to_crs(4326).copy()
    required = {province_code_col, province_name_col}
    missing = required.difference(provinces.columns)
    if missing:
        raise ValueError(f"Province boundary file misses columns: {sorted(missing)}")
    provinces[province_code_col] = provinces[province_code_col].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    provinces = provinces[[province_code_col, province_name_col, "geometry"]].dropna(subset=["geometry"]).reset_index(drop=True)
    provinces["geometry"] = provinces.geometry.make_valid()
    points = provinces.geometry.representative_point()

    production_vectors: dict[str, np.ndarray] = {}
    production_reference_year: int | None = None
    production_similarity_effective_date = pd.NaT
    if production is not None:
        if isinstance(production, pd.DataFrame):
            prod = production.copy()
        else:
            path = Path(production)
            prod = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        if not prod.empty and {"province_code", "commodity_code", "production_kg", "year"}.issubset(prod.columns):
            latest_year = int(pd.to_numeric(prod["year"], errors="coerce").max())
            production_reference_year = latest_year
            latest_production = prod[
                pd.to_numeric(prod["year"], errors="coerce").eq(latest_year)
            ]
            if "production_effective_date" in latest_production:
                production_similarity_effective_date = pd.to_datetime(
                    latest_production["production_effective_date"], errors="coerce"
                ).max()
            pivot = latest_production.pivot_table(
                index="province_code", columns="commodity_code", values="production_kg", aggfunc="sum"
            )
            pivot = np.log1p(pivot.fillna(0.0))
            production_vectors = {str(index).zfill(2): row.to_numpy(dtype=float) for index, row in pivot.iterrows()}

    all_pairs: list[dict[str, Any]] = []
    for i, j in combinations(range(len(provinces)), 2):
        source, target = provinces.iloc[i], provinces.iloc[j]
        source_code, target_code = str(source[province_code_col]), str(target[province_code_col])
        lon1, lat1 = points.iloc[i].x, points.iloc[i].y
        lon2, lat2 = points.iloc[j].x, points.iloc[j].y
        _, _, distance_m = GEOD.inv(lon1, lat1, lon2, lat2)
        vector_a, vector_b = production_vectors.get(source_code), production_vectors.get(target_code)
        similarity = _cosine_similarity(vector_a, vector_b) if vector_a is not None and vector_b is not None else np.nan
        all_pairs.append(
            {
                "source_province_code": source_code,
                "source_province_name": str(source[province_name_col]),
                "target_province_code": target_code,
                "target_province_name": str(target[province_name_col]),
                "adjacent_border": int(source.geometry.touches(target.geometry)),
                "centroid_distance_km": distance_m / 1000.0,
                "production_similarity": similarity,
                "production_reference_year": production_reference_year,
                "production_similarity_effective_date": production_similarity_effective_date,
            }
        )
    pair_frame = pd.DataFrame(all_pairs)
    selected_keys: set[tuple[str, str]] = set()
    for row in pair_frame[pair_frame["adjacent_border"].eq(1)].itertuples():
        selected_keys.add(tuple(sorted((row.source_province_code, row.target_province_code))))
    # Preserve island connectivity with k-nearest candidate edges per province.
    for code in provinces[province_code_col].astype(str):
        candidates = pair_frame[
            pair_frame["source_province_code"].eq(code) | pair_frame["target_province_code"].eq(code)
        ].nsmallest(int(knn), "centroid_distance_km")
        for row in candidates.itertuples():
            selected_keys.add(tuple(sorted((row.source_province_code, row.target_province_code))))

    base_selected_keys = set(selected_keys)
    transport_summary = pd.DataFrame()
    if transport_edges is not None:
        if isinstance(transport_edges, pd.DataFrame):
            transport = transport_edges.copy()
        else:
            transport_path = Path(transport_edges)
            transport = (
                pd.read_parquet(transport_path)
                if transport_path.suffix == ".parquet"
                else pd.read_csv(transport_path)
            )
        required_transport = {"source_province_code", "target_province_code", "edge_type"}
        if not transport.empty and required_transport.issubset(transport.columns):
            for column in ("source_province_code", "target_province_code"):
                transport[column] = (
                    transport[column]
                    .astype(str)
                    .str.replace(r"\.0$", "", regex=True)
                    .str.zfill(2)
                )
            ordered = transport.apply(
                lambda row: sorted(
                    (row["source_province_code"], row["target_province_code"])
                ),
                axis=1,
                result_type="expand",
            )
            transport[["source_province_code", "target_province_code"]] = ordered
            transport["length_km"] = pd.to_numeric(
                transport.get("length_km", 0.0), errors="coerce"
            ).fillna(0.0)
            transport["segment_count"] = pd.to_numeric(
                transport.get("segment_count", 0), errors="coerce"
            ).fillna(0)
            transport["osm_road_length_km"] = transport["length_km"].where(
                transport["edge_type"].eq("road_crossing"), 0.0
            )
            transport["osm_ferry_length_km"] = transport["length_km"].where(
                transport["edge_type"].eq("ferry_connection"), 0.0
            )
            transport_summary = (
                transport.groupby(
                    ["source_province_code", "target_province_code"], as_index=False
                )
                .agg(
                    osm_transport_segment_count=("segment_count", "sum"),
                    osm_road_length_km=("osm_road_length_km", "sum"),
                    osm_ferry_length_km=("osm_ferry_length_km", "sum"),
                    osm_transport_edge_types=(
                        "edge_type",
                        lambda values: "|".join(sorted(set(map(str, values)))),
                    ),
                    osm_snapshot_date=("snapshot_date", "max")
                    if "snapshot_date" in transport.columns
                    else ("edge_type", lambda _: pd.NaT),
                )
            )
            selected_keys.update(
                map(
                    tuple,
                    transport_summary[
                        ["source_province_code", "target_province_code"]
                    ].itertuples(index=False, name=None),
                )
            )

    selected = pair_frame[
        pair_frame.apply(
            lambda row: tuple(sorted((row["source_province_code"], row["target_province_code"]))) in selected_keys,
            axis=1,
        )
    ].copy()
    if not transport_summary.empty:
        selected = selected.merge(
            transport_summary,
            on=["source_province_code", "target_province_code"],
            how="left",
            validate="one_to_one",
        )
    selected["osm_transport_connection"] = selected.get(
        "osm_transport_segment_count", pd.Series(index=selected.index, dtype=float)
    ).fillna(0).gt(0).astype("int8")
    selected["edge_type"] = np.select(
        [
            selected["adjacent_border"].eq(1),
            selected.apply(
                lambda row: tuple(
                    sorted((row["source_province_code"], row["target_province_code"]))
                )
                in base_selected_keys,
                axis=1,
            ),
        ],
        ["border_adjacency", "distance_knn"],
        default="osm_transport_candidate",
    )
    selected["candidate_connectivity_only"] = 1
    selected["edge_id"] = selected[["source_province_code", "target_province_code"]].agg("--".join, axis=1)
    selected = selected.sort_values(["source_province_code", "target_province_code"]).reset_index(drop=True)
    outputs = save_frame(selected, output_base, save_csv=save_csv, save_parquet=save_parquet)
    return selected, outputs


def _best_lead_lag(source: pd.Series, target: pd.Series, max_lag: int, min_overlap: int) -> tuple[int, float, int]:
    best_lag, best_corr, best_overlap = 0, np.nan, 0
    for lag in range(0, int(max_lag) + 1):
        shifted_target = target.shift(-lag)
        aligned = pd.concat([source, shifted_target], axis=1).dropna()
        overlap = len(aligned)
        if overlap < min_overlap or aligned.iloc[:, 0].nunique() < 2 or aligned.iloc[:, 1].nunique() < 2:
            continue
        corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
        if np.isnan(best_corr) or abs(corr) > abs(best_corr):
            best_lag, best_corr, best_overlap = lag, corr, overlap
    return best_lag, best_corr, best_overlap


def _pairwise_cross_correlation(
    source: np.ndarray,
    target: np.ndarray,
    min_overlap: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Pairwise-complete column correlation for two aligned matrices."""
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    source_valid = np.isfinite(source)
    target_valid = np.isfinite(target)
    source_zero = np.where(source_valid, source, 0.0)
    target_zero = np.where(target_valid, target, 0.0)
    source_mask = source_valid.astype(float)
    target_mask = target_valid.astype(float)
    overlap = source_mask.T @ target_mask
    safe_overlap = np.where(overlap > 0, overlap, 1.0)
    source_sum = source_zero.T @ target_mask
    target_sum = source_mask.T @ target_zero
    cross_sum = source_zero.T @ target_zero
    source_square_sum = (source_zero**2).T @ target_mask
    target_square_sum = source_mask.T @ (target_zero**2)
    covariance = cross_sum - source_sum * target_sum / safe_overlap
    source_variance = source_square_sum - source_sum**2 / safe_overlap
    target_variance = target_square_sum - target_sum**2 / safe_overlap
    denominator = np.sqrt(
        np.maximum(source_variance, 0.0) * np.maximum(target_variance, 0.0)
    )
    correlation = np.divide(
        covariance,
        denominator,
        out=np.full_like(covariance, np.nan, dtype=float),
        where=(overlap >= int(min_overlap)) & (denominator > 0),
    )
    return correlation, overlap.astype(int)


def _best_lead_lag_matrix(
    values: np.ndarray,
    max_lag: int,
    min_overlap: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Find the strongest absolute future-target lag for every ordered pair."""
    values = np.asarray(values, dtype=float)
    width = values.shape[1]
    best_corr = np.full((width, width), np.nan, dtype=float)
    best_lag = np.zeros((width, width), dtype=int)
    best_overlap = np.zeros((width, width), dtype=int)
    for lag in range(int(max_lag) + 1):
        if lag:
            source, target = values[:-lag], values[lag:]
        else:
            source = target = values
        correlation, overlap = _pairwise_cross_correlation(
            source, target, min_overlap
        )
        better = np.isfinite(correlation) & (
            ~np.isfinite(best_corr) | (np.abs(correlation) > np.abs(best_corr))
        )
        best_corr[better] = correlation[better]
        best_lag[better] = lag
        best_overlap[better] = overlap[better]
    np.fill_diagonal(best_corr, np.nan)
    np.fill_diagonal(best_overlap, 0)
    return best_lag, best_corr, best_overlap


def build_dynamic_price_graph(
    prices: pd.DataFrame | str | Path,
    *,
    output_base: str | Path,
    window_days: int = 90,
    snapshot_freq: str = "MS",
    max_lag_days: int = 7,
    min_overlap: int = 30,
    top_k: int = 5,
    bounded_ffill_days: int = 3,
    shock_threshold: float = 0.10,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, dict[str, Path]]:
    if isinstance(prices, pd.DataFrame):
        data = prices.copy()
    else:
        path = Path(prices)
        data = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data["province_code"] = (
        data["province_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    )
    data = data.dropna(subset=["date", "province_code", "commodity_code", "market_level", "price_idr_per_kg"])
    rows: list[dict[str, Any]] = []
    for (commodity, market_level), group in data.groupby(["commodity_code", "market_level"]):
        pivot = group.pivot_table(index="date", columns="province_code", values="price_idr_per_kg", aggfunc="last").sort_index()
        pivot = pivot.asfreq("D").ffill(limit=int(bounded_ffill_days))
        returns = np.log(pivot.where(pivot.gt(0))).diff()
        shocks = pivot.pct_change(7, fill_method=None).ge(shock_threshold)
        if len(pivot) < window_days:
            continue
        snapshots = pd.date_range(pivot.index.min() + pd.Timedelta(days=window_days - 1), pivot.index.max(), freq=snapshot_freq)
        for snapshot in snapshots:
            start = snapshot - pd.Timedelta(days=window_days - 1)
            window_returns = returns.loc[start:snapshot]
            window_shocks = shocks.loc[start:snapshot]
            history_log_prices = np.log(pivot.loc[:snapshot].where(pivot.loc[:snapshot].gt(0)))
            seasonal_profiles = history_log_prices.groupby(
                history_log_prices.index.month
            ).mean()
            seasonal_profiles = seasonal_profiles - seasonal_profiles.mean(axis=0)
            provinces = [str(column) for column in window_returns.columns if window_returns[column].notna().sum() >= min_overlap]
            snapshot_rows: list[dict[str, Any]] = []
            return_values = window_returns[provinces].to_numpy(dtype=float)
            best_lag, best_corr, best_overlap = _best_lead_lag_matrix(
                return_values, max_lag_days, min_overlap
            )
            shock_values = (
                window_shocks[provinces].astype("boolean").fillna(False).to_numpy(dtype=bool)
            )
            seasonal_corr = seasonal_profiles[provinces].corr(min_periods=4)
            for source_index, source_code in enumerate(provinces):
                for target_index, target_code in enumerate(provinces):
                    if source_index == target_index:
                        continue
                    lag = int(best_lag[source_index, target_index])
                    corr = float(best_corr[source_index, target_index])
                    overlap = int(best_overlap[source_index, target_index])
                    if np.isnan(corr):
                        continue
                    source_shock = shock_values[:, source_index]
                    target_future_shock = np.zeros(len(shock_values), dtype=bool)
                    if lag:
                        target_future_shock[:-lag] = shock_values[lag:, target_index]
                    else:
                        target_future_shock = shock_values[:, target_index]
                    conditional = (
                        float(target_future_shock[source_shock].mean())
                        if source_shock.any()
                        else np.nan
                    )
                    cooccurrence = float(
                        (source_shock & shock_values[:, target_index]).mean()
                    )
                    seasonal_similarity = float(
                        seasonal_corr.loc[source_code, target_code]
                    )
                    snapshot_rows.append(
                        {
                            "snapshot_date": snapshot.normalize(),
                            "window_start": start.normalize(),
                            "window_days": int(window_days),
                            "commodity_code": commodity,
                            "market_level": market_level,
                            "source_province_code": source_code,
                            "target_province_code": target_code,
                            "lead_lag_corr": corr,
                            "abs_lead_lag_corr": abs(corr),
                            "source_lead_days": int(lag),
                            "overlap_days": int(overlap),
                            "shock_cooccurrence_rate": cooccurrence,
                            "target_shock_given_source": conditional,
                            "seasonal_similarity": seasonal_similarity,
                            "edge_interpretation": "model_inferred_price_dependence",
                        }
                    )
            if snapshot_rows:
                snapshot_frame = pd.DataFrame(snapshot_rows)
                snapshot_frame = (
                    snapshot_frame.sort_values(
                        ["source_province_code", "abs_lead_lag_corr"], ascending=[True, False]
                    )
                    .groupby("source_province_code", group_keys=False)
                    .head(int(top_k))
                )
                rows.extend(snapshot_frame.to_dict("records"))
    result = pd.DataFrame(rows)
    if not result.empty:
        result["edge_id"] = result[["snapshot_date", "commodity_code", "market_level", "source_province_code", "target_province_code"]].astype(str).agg("|".join, axis=1)
        result = result.sort_values(["snapshot_date", "commodity_code", "market_level", "source_province_code", "abs_lead_lag_corr"], ascending=[True, True, True, True, False]).reset_index(drop=True)
    outputs = save_frame(result, output_base, save_csv=save_csv, save_parquet=save_parquet)
    return result, outputs


def build_multilevel_graph(
    prices: pd.DataFrame,
    static_edges: pd.DataFrame,
    *,
    output_nodes_base: str | Path,
    output_edges_base: str | Path,
    save_csv: bool = True,
    save_parquet: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Path], dict[str, Path]]:
    node_columns = ["province_code", "province_name", "commodity_code", "commodity_name", "market_level"]
    nodes = prices[node_columns].drop_duplicates().copy()
    nodes["node_id"] = nodes[["province_code", "commodity_code", "market_level"]].astype(str).agg("|".join, axis=1)
    nodes = nodes.sort_values(node_columns).reset_index(drop=True)
    node_lookup = nodes.set_index(["province_code", "commodity_code", "market_level"])["node_id"].to_dict()

    edges: list[dict[str, Any]] = []
    # Cross-province structural edges are duplicated in both directions for message passing.
    for row in static_edges.to_dict("records"):
        for commodity in nodes["commodity_code"].dropna().unique():
            for market in nodes["market_level"].dropna().unique():
                source = node_lookup.get((str(row["source_province_code"]), commodity, market))
                target = node_lookup.get((str(row["target_province_code"]), commodity, market))
                if not source or not target:
                    continue
                for source_node, target_node in ((source, target), (target, source)):
                    edges.append(
                        {
                            "source_node": source_node,
                            "target_node": target_node,
                            "edge_type": "cross_province_structural",
                            "static_edge_type": row.get("edge_type"),
                            "adjacent_border": row.get("adjacent_border"),
                            "centroid_distance_km": row.get("centroid_distance_km"),
                            "production_similarity": row.get("production_similarity"),
                            "production_reference_year": row.get(
                                "production_reference_year"
                            ),
                            "production_similarity_effective_date": row.get(
                                "production_similarity_effective_date"
                            ),
                            "osm_transport_connection": row.get("osm_transport_connection"),
                            "osm_transport_segment_count": row.get("osm_transport_segment_count"),
                            "osm_road_length_km": row.get("osm_road_length_km"),
                            "osm_ferry_length_km": row.get("osm_ferry_length_km"),
                            "candidate_connectivity_only": row.get(
                                "candidate_connectivity_only", 1
                            ),
                        }
                    )
    # Producer -> wholesale -> retail links within each province and commodity.
    market_links = [("producer", "wholesale"), ("wholesale", "retail"), ("producer", "retail")]
    for province, commodity in nodes[["province_code", "commodity_code"]].drop_duplicates().itertuples(index=False):
        for source_market, target_market in market_links:
            source = node_lookup.get((str(province), commodity, source_market))
            target = node_lookup.get((str(province), commodity, target_market))
            if source and target:
                edges.append(
                    {
                        "source_node": source,
                        "target_node": target,
                        "edge_type": "market_level_link",
                        "static_edge_type": "within_province_market_hierarchy",
                        "adjacent_border": 0,
                        "centroid_distance_km": 0.0,
                        "production_similarity": 1.0,
                        "osm_transport_connection": 0,
                        "osm_transport_segment_count": 0,
                        "osm_road_length_km": 0.0,
                        "osm_ferry_length_km": 0.0,
                        "candidate_connectivity_only": 1,
                    }
                )
    edge_frame = pd.DataFrame(edges).drop_duplicates(["source_node", "target_node", "edge_type"])
    if not edge_frame.empty:
        edge_frame["edge_id"] = edge_frame[["source_node", "target_node", "edge_type"]].agg("|".join, axis=1)
    node_outputs = save_frame(nodes, output_nodes_base, save_csv=save_csv, save_parquet=save_parquet)
    edge_outputs = save_frame(edge_frame, output_edges_base, save_csv=save_csv, save_parquet=save_parquet)
    return nodes, edge_frame, node_outputs, edge_outputs
