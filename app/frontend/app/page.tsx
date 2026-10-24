"use client";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BellRing,
  Globe2,
  Info,
  MapPin,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Forecast, WarningLevel } from "@/lib/types";
import { useForecastContext } from "@/lib/useForecastContext";
import {
  forecastsToCsv,
  rankForecasts,
  summarizeForecasts,
  WARNING_COLORS,
} from "@/lib/overview.mjs";
import { FilterBar } from "@/components/filters/FilterBar";
import { StatusBadge } from "@/components/common/StatusBadge";
import { idr, pct, shortDate } from "@/components/common/format";
import { ForecastTable } from "@/components/overview/ForecastTable";
import { ProvinceInsight } from "@/components/overview/ProvinceInsight";
const IndonesiaMap = dynamic(
  () => import("@/components/map/IndonesiaMap").then((m) => m.IndonesiaMap),
  { ssr: false, loading: () => <div className="skeleton h-full w-full" /> },
);

export default function OverviewPage() {
  const { state, metadata, ready, params } = useForecastContext(true);
  const [mapReset, setMapReset] = useState(0);
  const forecasts = useQuery({
    queryKey: ["forecasts", params],
    queryFn: () => api.forecasts(params),
    enabled: ready,
  });
  const geojson = useQuery({
    queryKey: ["provinces", params],
    queryFn: () => api.provinces(params),
    enabled: ready,
  });
  const rows = forecasts.data || [];
  const summary = useMemo(
    () => summarizeForecasts(forecasts.data || []),
    [forecasts.data],
  );
  const priority = useMemo(
    () => rankForecasts(forecasts.data || []).slice(0, 5),
    [forecasts.data],
  );
  const selected = rows.find(
    (row) => row.province_code === state.selectedProvince,
  );
  const selectedName = geojson.data?.features.find(
    (x) => String(x.properties.province_code) === state.selectedProvince,
  )?.properties.province_name;
  const selectProvince = (code: string, id = "") => {
    state.set({
      selectedProvince: code,
      selectedForecastId: id,
      reveal: false,
    });
    if (window.innerWidth < 768)
      requestAnimationFrame(() =>
        document
          .getElementById("province-insight")
          ?.scrollIntoView({
            behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
              .matches
              ? "instant"
              : "smooth",
            block: "start",
          }),
      );
  };
  const select = (row: Forecast) =>
    selectProvince(row.province_code, row.forecast_id);
  const nationalView = () => {
    state.set({ selectedProvince: "", selectedForecastId: "", reveal: false });
    setMapReset((x) => x + 1);
  };
  const exportSnapshot = () => {
    const url = URL.createObjectURL(
      new Blob(["\ufeff", forecastsToCsv(rows)], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `pasarpulse-${state.commodity}-${state.marketLevel}-${state.origin}-${state.horizon}d.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  if (metadata.isError)
    return (
      <div className="surface empty-state">
        <TriangleAlert size={28} />
        <h2>The workspace is temporarily unavailable</h2>
        <p>We could not retrieve the market snapshot. Please try again.</p>
        <button
          className="ui-button mt-5"
          onClick={() => void metadata.refetch()}
        >
          <RotateCcw size={14} />
          Try again
        </button>
      </div>
    );
  if (!metadata.data) return <OverviewLoading />;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">National monitoring</div>
          <h1>Market overview</h1>
          <p>A clearer view of where food prices may move next.</p>
        </div>
        <button
          className="ui-button"
          onClick={exportSnapshot}
          disabled={!rows.length}
          aria-label="Export forecast snapshot"
        >
          <ArrowDownToLine size={15} />
          <span className="export-label">Export snapshot</span>
        </button>
      </div>
      <FilterBar metadata={metadata.data} />
      {forecasts.isError ? (
        <div className="surface empty-state">
          <TriangleAlert size={24} />
          <h2>Forecast snapshot unavailable</h2>
          <p>Please retry, or choose another forecast date.</p>
          <button
            className="ui-button mt-4"
            onClick={() => void forecasts.refetch()}
          >
            Retry forecasts
          </button>
        </div>
      ) : !ready || forecasts.isPending ? (
        <OverviewLoading compact />
      ) : (
        <>
          <section className="summary-grid" aria-label="Snapshot summary">
            <article className="summary-card">
              <div className="summary-top">
                Provinces covered
                <span className="summary-icon">
                  <Globe2 size={17} strokeWidth={1.6} />
                </span>
              </div>
              <strong>
                {summary.provinces}
                <small>/ {metadata.data.province_count_in_geometry}</small>
              </strong>
              <p>With forecasts in this snapshot</p>
              <div className="summary-bars">
                <span
                  style={{ background: "#7c9b71", flex: summary.provinces }}
                />
                <span
                  style={{
                    background: "#e8ede3",
                    flex: Math.max(
                      0,
                      metadata.data.province_count_in_geometry -
                        summary.provinces,
                    ),
                  }}
                />
              </div>
            </article>
            <article className="summary-card">
              <div className="summary-top">
                Provinces to review
                <span className="summary-icon">
                  <BellRing size={17} strokeWidth={1.6} />
                </span>
              </div>
              <strong>
                {summary.attention}
                <small>provinces</small>
              </strong>
              <p>Projected rise ≥ {metadata.data.warning_thresholds.watch}%</p>
              <div className="summary-bars">
                {(
                  [
                    "HIGH",
                    "ELEVATED",
                    "WATCH",
                    "STABLE",
                    "INSUFFICIENT",
                  ] as WarningLevel[]
                )
                  .filter((level) => summary.counts[level])
                  .map((level) => (
                    <span
                      key={level}
                      title={`${level}: ${summary.counts[level]}`}
                      style={{
                        background: WARNING_COLORS[level],
                        flex: summary.counts[level],
                      }}
                    />
                  ))}
              </div>
            </article>
            <article className="summary-card">
              <div className="summary-top">
                Highest projected change
                <span className="summary-icon">
                  <ArrowUpRight size={18} strokeWidth={1.6} />
                </span>
              </div>
              <strong>
                {summary.largest
                  ? pct(summary.largest.projected_change_pct)
                  : "—"}
              </strong>
              <p>
                {summary.largest?.province_name || "No forecast available"} ·{" "}
                {state.horizon}-day outlook
              </p>
              <div className="mt-3.5 text-[10px] font-medium text-[#537349]">
                As of {shortDate(state.origin)}
              </div>
            </article>
          </section>
          <div className="monitor-grid">
            <section
              className="surface map-card"
              aria-label="National price outlook"
            >
              <div className="surface-heading">
                <div>
                  <h2>Indonesia at a glance</h2>
                  <p>Select a province to explore its forecast.</p>
                </div>
                <div className="segmented" aria-label="Map layer">
                  {[
                    { key: "risk", label: "Warning" },
                    { key: "change", label: "Price change" },
                    { key: "evidence", label: "Evidence" },
                  ].map((item) => (
                    <button
                      key={item.key}
                      aria-pressed={state.layer === item.key}
                      onClick={() => state.set({ layer: item.key })}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="map-canvas">
                {geojson.isError ? (
                  <div className="empty-state">
                    <p>The map could not be loaded.</p>
                    <button
                      className="ui-button mt-3"
                      onClick={() => void geojson.refetch()}
                    >
                      Retry map
                    </button>
                    <p className="mt-3">
                      You can still explore forecasts in the table below.
                    </p>
                  </div>
                ) : (
                  <IndonesiaMap
                    geojson={geojson.data}
                    layer={state.layer}
                    selectedProvince={state.selectedProvince}
                    resetKey={mapReset}
                    onSelect={selectProvince}
                  />
                )}
              </div>
              <div className="map-footer">
                <MapLegend layer={state.layer} />
                <button className="ui-link text-[10px]" onClick={nationalView}>
                  <RotateCcw size={11} />
                  National view
                </button>
              </div>
            </section>
            {state.selectedProvince ? (
              selected ? (
                <ProvinceInsight
                  key={selected.forecast_id}
                  forecast={selected}
                  onClose={nationalView}
                />
              ) : (
                <section className="surface panel-enter empty-state">
                  <MapPin size={24} />
                  <h2>{String(selectedName || "Selected province")}</h2>
                  <p>
                    No forecast is available for this province in the selected
                    snapshot.
                  </p>
                  <button className="ui-link mt-5" onClick={nationalView}>
                    Back to national view <ArrowRight size={13} />
                  </button>
                </section>
              )
            ) : (
              <section className="surface">
                <div className="surface-heading">
                  <div>
                    <h2>
                      {summary.attention
                        ? "Priorities to review"
                        : "Regional outlook"}
                    </h2>
                    <p>
                      {summary.attention
                        ? "Ranked by projected price increase"
                        : "No price-rise warnings in this snapshot"}
                    </p>
                  </div>
                  <span className="summary-icon">
                    <MapPin size={16} />
                  </span>
                </div>
                <div className="priority-list">
                  {priority.map((row, i) => (
                    <button
                      key={row.forecast_id}
                      className="priority-item"
                      onClick={() => select(row)}
                    >
                      <span className="priority-number">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="priority-copy">
                        <b>{row.province_name}</b>
                        <small>{idr(row.predicted_price)} / kg</small>
                      </span>
                      <span className="priority-change">
                        <b
                          className={
                            row.projected_change_pct <= 0
                              ? "!text-[#285c45]"
                              : ""
                          }
                        >
                          {pct(row.projected_change_pct)}
                        </b>
                        <StatusBadge label={row.warning_level} />
                      </span>
                    </button>
                  ))}
                </div>
                {!priority.length && (
                  <div className="empty-state">
                    No forecasts for the selected context.
                  </div>
                )}
                <div className="panel-bottom">
                  <span>{summary.attention} above watch threshold</span>
                  <Link className="ui-link" href="/alerts">
                    View alert queue <ArrowRight size={13} />
                  </Link>
                </div>
              </section>
            )}
          </div>
          <ForecastTable
            rows={rows}
            selected={state.selectedProvince}
            onSelect={select}
          />
          <div className="notice mt-5">
            <Info size={15} />
            <span>
              <strong>Forecast as of {shortDate(state.origin)}.</strong> Warning
              levels follow configured price-rise thresholds; they are not model
              probabilities or official regulatory thresholds. Historical replay
              uses saved forecasts.
            </span>
          </div>
        </>
      )}
    </>
  );
}
function MapLegend({ layer }: { layer: string }) {
  if (layer === "change")
    return (
      <div className="map-legend" aria-label="Projected change scale">
        {[
          { text: "Decline", color: "#7c9b71" },
          { text: "0%", color: "#e1e9d5" },
          { text: "+5%", color: "#d6bc74" },
          { text: "+10%", color: "#cd966b" },
          { text: "+20%", color: "#b34b3e" },
        ].map((item) => (
          <span key={item.text}>
            <i style={{ background: item.color }} />
            {item.text}
          </span>
        ))}
      </div>
    );
  if (layer === "evidence")
    return (
      <div className="map-legend">
        <span>
          <i style={{ background: "#7c9b71" }} />
          Context available
        </span>
        <span>
          <i style={{ background: "#d2dcd0" }} />
          Insufficient
        </span>
      </div>
    );
  return (
    <div className="map-legend">
      {(
        [
          "STABLE",
          "WATCH",
          "ELEVATED",
          "HIGH",
          "INSUFFICIENT",
        ] as WarningLevel[]
      ).map((level) => (
        <span key={level}>
          <i style={{ background: WARNING_COLORS[level] }} />
          {level === "INSUFFICIENT"
            ? "No forecast"
            : level.charAt(0) + level.slice(1).toLowerCase()}
        </span>
      ))}
    </div>
  );
}
function OverviewLoading({ compact = false }: { compact?: boolean }) {
  return (
    <div role="status" aria-label="Loading market snapshot">
      {!compact && <div className="skeleton h-20 mb-6" />}
      <div className="summary-grid">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton h-36" />
        ))}
      </div>
      <div className="skeleton h-[480px]" />
      <span className="sr-only">Loading market snapshot…</span>
    </div>
  );
}
