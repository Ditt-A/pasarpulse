"""Presentation-ready diagnostic figures for the ingestion notebook."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    return path


def plot_modality_coverage(frame: pd.DataFrame, output: str | Path) -> tuple[plt.Figure, Path]:
    columns = ["mask_price", "mask_weather", "mask_production", "mask_satellite", "mask_calendar"]
    available = [column for column in columns if column in frame]
    values = [100 * pd.to_numeric(frame[column], errors="coerce").mean() for column in available]
    labels = [column.removeprefix("mask_").title() for column in available]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, values)
    ax.set_ylabel("Coverage (%)")
    ax.set_ylim(0, 100)
    ax.set_title("National modality availability")
    for index, value in enumerate(values):
        ax.text(index, min(value + 2, 98), f"{value:.1f}%", ha="center")
    return fig, _save(fig, Path(output))


def plot_price_series(
    frame: pd.DataFrame,
    output: str | Path,
    *,
    province_code: str = "",
    commodity_code: str = "CRM",
    market_level: str = "retail",
) -> tuple[plt.Figure, Path]:
    data = frame.copy()
    if not province_code and "province_code" in data and not data.empty:
        candidates = data.loc[
            data["commodity_code"].eq(commodity_code) & data["market_level"].eq(market_level)
        ].groupby("province_code")["price_idr_per_kg"].count()
        province_code = str(candidates.idxmax()) if not candidates.empty else str(data["province_code"].dropna().iloc[0])
    selected = data[
        data["province_code"].astype(str).eq(str(province_code))
        & data["commodity_code"].eq(commodity_code)
        & data["market_level"].eq(market_level)
    ].sort_values("date")
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(pd.to_datetime(selected["date"]), selected["price_idr_per_kg"], label="Observed price", linewidth=1.2)
    if "price_ffill" in selected:
        ax.plot(pd.to_datetime(selected["date"]), selected["price_ffill"], label="Bounded carry-forward", linewidth=0.9, alpha=0.7)
    title_name = selected["province_name"].dropna().iloc[0] if not selected.empty and "province_name" in selected else province_code
    ax.set_title(f"Price series: {title_name} · {commodity_code} · {market_level}")
    ax.set_ylabel("IDR per kg")
    ax.set_xlabel("Date")
    ax.legend()
    return fig, _save(fig, Path(output))


def plot_series_eligibility(audit: pd.DataFrame, output: str | Path) -> tuple[plt.Figure, Path]:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    if audit.empty:
        ax.text(0.5, 0.5, "Price coverage audit is empty", ha="center", va="center")
        ax.set_axis_off()
    else:
        counts = audit["eligible"].fillna(False).map({True: "Eligible", False: "Insufficient evidence"}).value_counts()
        ax.bar(counts.index, counts.values)
        ax.set_ylabel("Number of series")
        ax.set_title("Price-series eligibility contract")
        for index, value in enumerate(counts.values):
            ax.text(index, value, str(int(value)), ha="center", va="bottom")
    return fig, _save(fig, Path(output))


def plot_top_production(
    production: pd.DataFrame,
    output: str | Path,
    *,
    commodity_code: str = "CRM",
    top_n: int = 12,
) -> tuple[plt.Figure, Path]:
    fig, ax = plt.subplots(figsize=(9, 5.5))
    if production.empty:
        ax.text(0.5, 0.5, "Production data is empty", ha="center", va="center")
        ax.set_axis_off()
    else:
        data = production.copy()
        latest_year = pd.to_numeric(data["year"], errors="coerce").max()
        selected = data[
            data["commodity_code"].eq(commodity_code)
            & pd.to_numeric(data["year"], errors="coerce").eq(latest_year)
        ].nlargest(int(top_n), "production_kg").sort_values("production_kg")
        ax.barh(selected["province_name"], selected["production_kg"])
        ax.set_xlabel("Production (kg)")
        ax.set_title(f"Top producing provinces · {commodity_code} · {int(latest_year) if pd.notna(latest_year) else ''}")
    return fig, _save(fig, Path(output))


def plot_missingness_by_month(frame: pd.DataFrame, output: str | Path) -> tuple[plt.Figure, Path]:
    fig, ax = plt.subplots(figsize=(10, 4.8))
    mask_columns = [column for column in ["mask_price", "mask_weather", "mask_production", "mask_satellite"] if column in frame]
    if not mask_columns:
        ax.text(0.5, 0.5, "No modality masks found", ha="center", va="center")
        ax.set_axis_off()
    else:
        data = frame.copy()
        data["month"] = pd.to_datetime(data["date"]).dt.to_period("M").dt.to_timestamp()
        monthly = data.groupby("month")[mask_columns].mean() * 100
        for column in mask_columns:
            ax.plot(monthly.index, monthly[column], label=column.removeprefix("mask_").title())
        ax.set_ylabel("Available rows (%)")
        ax.set_ylim(0, 100)
        ax.set_title("Modality availability through time")
        ax.legend(ncol=2)
    return fig, _save(fig, Path(output))


def create_pipeline_figures(
    *,
    ready: pd.DataFrame,
    coverage_audit: pd.DataFrame,
    production: pd.DataFrame,
    output_dir: str | Path,
    example_province: str = "",
    example_commodity: str = "CRM",
    example_market_level: str = "retail",
    top_n_production: int = 12,
    close_figures: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    figures: dict[str, Any] = {}
    figures["modality_coverage"] = plot_modality_coverage(ready, output_dir / "01_modality_coverage.png")
    figures["price_series"] = plot_price_series(
        ready, output_dir / "02_example_price_series.png",
        province_code=example_province, commodity_code=example_commodity, market_level=example_market_level,
    )
    figures["series_eligibility"] = plot_series_eligibility(coverage_audit, output_dir / "03_series_eligibility.png")
    figures["top_production"] = plot_top_production(
        production, output_dir / "04_top_production.png", commodity_code=example_commodity, top_n=top_n_production,
    )
    figures["monthly_missingness"] = plot_missingness_by_month(ready, output_dir / "05_monthly_modality_availability.png")
    if close_figures:
        for figure, _ in figures.values():
            plt.close(figure)
    return figures
