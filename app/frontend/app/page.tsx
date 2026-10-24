"use client";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Download,
  Info,
  List,
  Map as MapIcon,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Forecast, WarningLevel } from "@/lib/types";
import { useForecastContext } from "@/lib/useForecastContext";
import {
  forecastsToCsv,
  rankForecasts,
  summarizeForecasts,
  WARNING_COLORS,
  type RankingOptions,
} from "@/lib/overview.mjs";
import { FilterBar } from "@/components/filters/FilterBar";
import { ForecastTable } from "@/components/overview/ForecastTable";
import { ProvinceInsight } from "@/components/overview/ProvinceInsight";
import { RequestState } from "@/components/common/RequestState";
const IndonesiaMap = dynamic(
  () => import("@/components/map/IndonesiaMap").then((m) => m.IndonesiaMap),
  { ssr: false, loading: () => <div className="skeleton h-full w-full" /> },
);
export default function OverviewPage() {
  const { state, metadata, ready, params } = useForecastContext(true);
  const [sort, setSort] = useState<NonNullable<RankingOptions["sort"]>>(
    "projected_change_pct",
  );
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [mapReset, setMapReset] = useState(0);
  const [compact, setCompact] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const forecasts = useQuery({
    queryKey: ["forecasts", params],
    queryFn: () => api.forecasts(params),
    enabled: ready,
  });
  const all = forecasts.data || [];
  const selected = all.find(
    (row) => row.province_code === state.selectedProvince,
  );
  const geojson = useQuery({
    queryKey: ["provinces", params],
    queryFn: () => api.provinces(params),
    enabled:
      ready &&
      (state.view === "map" ||
        Boolean(state.selectedProvince && !selected && !forecasts.isPending)),
  });
  const summary = useMemo(
    () => summarizeForecasts(forecasts.data || []),
    [forecasts.data],
  );
  const rows = useMemo(
    () =>
      rankForecasts(forecasts.data || [], {
        search: state.search,
        warning: state.risk,
        sort,
        direction,
      }),
    [forecasts.data, state.search, state.risk, sort, direction],
  );
  const filtered = Boolean(state.search.trim() || state.risk !== "ALL");
  const visibleCodes = useMemo(
    () => (filtered ? rows.map((row) => row.province_code) : undefined),
    [filtered, rows],
  );
  const selectedName = geojson.data?.features.find(
    (x) => String(x.properties.province_code) === state.selectedProvince,
  )?.properties.province_name;
  const loading = !ready || forecasts.isPending;
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1050px)");
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!compact || !state.selectedProvince) {
      dialog.current?.close();
      return;
    }
    dialog.current?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [compact, state.selectedProvince]);
  const close = () => {
    const code = state.selectedProvince;
    state.set({ selectedProvince: "", selectedForecastId: "", reveal: false });
    requestAnimationFrame(() =>
      document
        .querySelector<HTMLButtonElement>(`button[data-province="${code}"]`)
        ?.focus({ preventScroll: true }),
    );
  };
  const choose = (code: string, id = "") =>
    state.set({
      selectedProvince: code,
      selectedForecastId: id,
      reveal: false,
    });
  const resetList = () =>
    state.set({
      search: "",
      risk: "ALL",
      selectedProvince: "",
      selectedForecastId: "",
      reveal: false,
    });
  const changeRisk = (risk: string) =>
    state.set({
      risk,
      selectedProvince: "",
      selectedForecastId: "",
      reveal: false,
    });
  const changeSort = (key: NonNullable<RankingOptions["sort"]>) => {
    setSort(key);
    setDirection(
      sort === key
        ? direction === "desc"
          ? "asc"
          : "desc"
        : key === "province_name"
          ? "asc"
          : "desc",
    );
  };
  const changeView = (view: "list" | "map") => state.set({ view });
  const exportSnapshot = () => {
    const url = URL.createObjectURL(
      new Blob(["\ufeff", forecastsToCsv(rows)], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `pasarpulse-${state.commodity}-${state.marketLevel}-${state.origin}-${state.horizon}h.csv`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const detail = selected ? (
    <ProvinceInsight
      key={selected.forecast_id}
      forecast={selected}
      onClose={close}
    />
  ) : (
    <section
      className="province-insight empty-state"
      aria-label="Detail wilayah"
    >
      <button className="ui-link mb-5" onClick={close}>
        <X size={14} />
        Tutup detail
      </button>
      <h2>{String(selectedName || "Wilayah terpilih")}</h2>
      <p>
        {loading
          ? "Memuat proyeksi…"
          : "Belum ada proyeksi untuk provinsi ini pada snapshot yang dipilih."}
      </p>
      <p className="mt-3">
        Pilihan komoditas, pasar, dan tanggal tetap dipertahankan.
      </p>
    </section>
  );
  if (metadata.isError)
    return <RequestState error retry={() => void metadata.refetch()} />;
  return (
    <>
      <div className="monitor-heading">
        <div className="heading-context">
          <h1>Pemantauan harga</h1>
          <span>Proyeksi antarprovinsi</span>
        </div>
        <button
          className="ui-button"
          onClick={exportSnapshot}
          disabled={loading || !rows.length}
          aria-label="Ekspor hasil pemantauan"
        >
          <Download size={14} />
          <span className="export-label">Ekspor CSV</span>
        </button>
      </div>
      <div className="monitor-filters">
        {metadata.data ? (
          <FilterBar metadata={metadata.data} />
        ) : (
          <div className="skeleton my-4 h-8" />
        )}
      </div>
      <div className="monitor-toolbar">
        <div className="toolbar-left">
          <div className="scope-tabs" aria-label="Cakupan pemantauan">
            <button
              aria-pressed={state.risk === "ALL"}
              onClick={() => changeRisk("ALL")}
            >
              Semua<span>{loading ? "—" : summary.provinces}</span>
            </button>
            <button
              aria-pressed={state.risk === "ATTENTION"}
              onClick={() => changeRisk("ATTENTION")}
            >
              Perlu diperiksa<span>{loading ? "—" : summary.attention}</span>
            </button>
          </div>
          <select
            className="warning-select"
            aria-label="Tingkat peringatan"
            value={
              ["ALL", "ATTENTION"].includes(state.risk) ? "ALL" : state.risk
            }
            onChange={(e) => changeRisk(e.target.value)}
          >
            <option value="ALL">Semua tingkat</option>
            <option value="HIGH">Tinggi</option>
            <option value="ELEVATED">Meningkat</option>
            <option value="WATCH">Waspada</option>
            <option value="STABLE">Stabil</option>
            <option value="INSUFFICIENT">Data terbatas</option>
          </select>
        </div>
        <div className="toolbar-right">
          <label className="search-field">
            <Search size={14} />
            <input
              aria-label="Cari provinsi"
              placeholder="Cari provinsi…"
              value={state.search}
              maxLength={80}
              onChange={(e) =>
                state.set({
                  search: e.target.value,
                  selectedProvince: "",
                  selectedForecastId: "",
                  reveal: false,
                })
              }
            />
            {state.search && (
              <button
                aria-label="Hapus pencarian"
                onClick={() => state.set({ search: "" })}
              >
                <X size={13} />
              </button>
            )}
          </label>
          <div
            className="segmented"
            role="tablist"
            aria-label="Tampilan pemantauan"
          >
            {(
              [
                { key: "list", label: "Daftar", icon: List },
                { key: "map", label: "Peta", icon: MapIcon },
              ] as const
            ).map(({ key, label, icon: Icon }) => (
              <button
                role="tab"
                key={key}
                id={`view-${key}`}
                aria-selected={state.view === key}
                aria-controls="monitor-view"
                tabIndex={state.view === key ? 0 : -1}
                onClick={() => changeView(key)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                    e.preventDefault();
                    const next = key === "list" ? "map" : "list";
                    changeView(next);
                    document.getElementById(`view-${next}`)?.focus();
                  }
                }}
              >
                <Icon size={12} className="mr-1.5 inline" />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="monitor-summary">
        <div className="summary-scope">
          <strong>
            {loading
              ? "Memuat proyeksi…"
              : `${rows.length}${filtered ? ` dari ${summary.provinces}` : ""} provinsi`}
          </strong>
          <span>·</span>
          <span>
            {metadata.data?.province_count_in_geometry ?? "—"} wilayah pada peta
          </span>
          <span>·</span>
          <span>Rp/kg</span>
        </div>
        <span className="summary-help" title={metadata.data?.warning_note}>
          <Info size={11} className="mr-1 inline" />
          Peringatan mengikuti batas kenaikan harga.
        </span>
      </div>
      <div className="monitor-body">
        <div
          id="monitor-view"
          className="monitor-content"
          role="tabpanel"
          aria-labelledby={`view-${state.view}`}
        >
          {forecasts.isError ? (
            <RequestState error retry={() => void forecasts.refetch()} />
          ) : state.view === "list" ? (
            <ForecastTable
              rows={rows}
              selected={state.selectedProvince}
              onSelect={(row: Forecast) =>
                choose(row.province_code, row.forecast_id)
              }
              sort={sort}
              direction={direction}
              onSort={changeSort}
              onClear={resetList}
              loading={loading}
              horizon={state.horizon}
            />
          ) : (
            <section className="map-view" aria-label="Peta proyeksi provinsi">
              <div className="map-tools">
                <label>
                  Lapisan
                  <select
                    aria-label="Lapisan peta"
                    value={state.layer}
                    onChange={(e) => state.set({ layer: e.target.value })}
                  >
                    <option value="risk">Tingkat peringatan</option>
                    <option value="change">Perubahan harga</option>
                    <option value="evidence">Ketersediaan data</option>
                  </select>
                </label>
                <span>Pilih wilayah untuk membuka detail</span>
                <button
                  className="ui-link"
                  onClick={() => {
                    close();
                    setMapReset((x) => x + 1);
                  }}
                >
                  <RotateCcw size={12} />
                  Nasional
                </button>
              </div>
              <div className="map-canvas">
                {geojson.isPending ? (
                  <div role="status" className="empty-state">
                    Memuat peta...
                  </div>
                ) : geojson.isError ? (
                  <RequestState error retry={() => void geojson.refetch()} />
                ) : (
                  <IndonesiaMap
                    geojson={geojson.data}
                    layer={state.layer}
                    selectedProvince={state.selectedProvince}
                    visibleProvinces={visibleCodes}
                    resetKey={mapReset}
                    onSelect={choose}
                  />
                )}{" "}
                {!loading && filtered && !rows.length && (
                  <div className="map-empty">
                    Tidak ada hasil.{" "}
                    <button className="ui-link" onClick={resetList}>
                      Hapus filter
                    </button>
                  </div>
                )}
              </div>
              <div className="map-footer">
                <MapLegend layer={state.layer} filtered={filtered} />
              </div>
            </section>
          )}
        </div>
        {state.selectedProvince && !compact && (
          <aside
            className="monitor-inspector"
            aria-label="Panel detail provinsi"
          >
            {detail}
          </aside>
        )}
      </div>
      <dialog
        ref={dialog}
        className="detail-dialog"
        aria-label="Detail provinsi"
        onCancel={close}
        onClick={(e) => {
          if (e.target === e.currentTarget) close();
        }}
      >
        {compact && state.selectedProvince && detail}
      </dialog>
    </>
  );
}
function MapLegend({ layer, filtered }: { layer: string; filtered: boolean }) {
  const labels: Record<WarningLevel, string> = {
    STABLE: "Stabil",
    WATCH: "Waspada",
    ELEVATED: "Meningkat",
    HIGH: "Tinggi",
    INSUFFICIENT: filtered ? "Di luar filter" : "Belum ada proyeksi",
  };
  if (layer === "change")
    return (
      <div className="map-legend">
        {[
          { label: "Turun", color: "#7c9b71" },
          { label: "0%", color: "#e1e9d5" },
          { label: "+5%", color: "#d6bc74" },
          { label: "+10%", color: "#cd966b" },
          { label: "+20%", color: "#b34b3e" },
        ].map((item) => (
          <span key={item.label}>
            <i style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
    );
  if (layer === "evidence")
    return (
      <div className="map-legend">
        <span>
          <i style={{ background: "#7c9b71" }} />
          Konteks tersedia
        </span>
        <span>
          <i style={{ background: "#d2dcd0" }} />
          {filtered ? "Di luar filter" : "Data terbatas"}
        </span>
      </div>
    );
  return (
    <div className="map-legend">
      {(Object.keys(labels) as WarningLevel[]).map((level) => (
        <span key={level}>
          <i style={{ background: WARNING_COLORS[level] }} />
          {labels[level]}
        </span>
      ))}
    </div>
  );
}
