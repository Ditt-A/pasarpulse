"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell, CalendarDays, ChevronLeft, ChevronRight, Menu, MessageCircle, Search, SlidersHorizontal, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Alert, Forecast, ForecastXai, Metadata } from "@/lib/types";
import { useDashboardStore } from "@/stores/dashboard";
import { FilterBar } from "@/components/filters/FilterBar";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";

const IndonesiaMap = dynamic(() => import("@/components/map/IndonesiaMap").then((module) => module.IndonesiaMap), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-slate-100" />,
});

export default function OverviewPage() {
  const router = useRouter();
  const state = useDashboardStore();
  const setDashboard = useDashboardStore((value) => value.set);
  const setCopilotOpen = useDashboardStore((value) => value.setCopilotOpen);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);

  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });

  useEffect(() => {
    if (metadata.data?.latest_origin && !state.origin) setDashboard({ origin: metadata.data.latest_origin });
  }, [metadata.data?.latest_origin, setDashboard, state.origin]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const values: Record<string, unknown> = {};
    if (params.get("province")) values.selectedProvince = params.get("province");
    if (params.get("commodity")) values.commodity = params.get("commodity");
    if (params.get("market")) values.marketLevel = params.get("market");
    if (params.get("horizon")) values.horizon = Number(params.get("horizon"));
    if (params.get("origin")) values.origin = params.get("origin");
    if (Object.keys(values).length) setDashboard(values as never);
  }, [setDashboard]);

  useEffect(() => {
    if (!state.origin) return;
    const params = new URLSearchParams({
      commodity: state.commodity,
      market: state.marketLevel,
      horizon: String(state.horizon),
      origin: state.origin,
    });
    if (state.selectedProvince) params.set("province", state.selectedProvince);
    window.history.replaceState(null, "", `/?${params.toString()}`);
  }, [state.commodity, state.horizon, state.marketLevel, state.origin, state.selectedProvince]);

  const params = { origin: state.origin || undefined, commodity: state.commodity, market_level: state.marketLevel, horizon: state.horizon };
  const forecasts = useQuery({ queryKey: ["forecasts", params], queryFn: () => api.forecasts(params), enabled: Boolean(metadata.data) });
  const alerts = useQuery({ queryKey: ["alerts", params], queryFn: () => api.alerts({ ...params, limit: 100 }), enabled: Boolean(metadata.data) });
  const geojson = useQuery({ queryKey: ["provinces", params], queryFn: () => api.provinces(params), enabled: Boolean(metadata.data) });

  const selected = forecasts.data?.find((item) => item.province_code === state.selectedProvince) || forecasts.data?.[0];
  const selectedForCard = state.selectedProvince ? selected : undefined;
  const locations = useMemo(() => {
    const byCode = new Map<string, { code: string; name: string }>();
    (forecasts.data || []).forEach((item) => byCode.set(item.province_code, { code: item.province_code, name: item.province_name }));
    return Array.from(byCode.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [forecasts.data]);
  const filteredLocations = useMemo(() => {
    const q = search.trim().toLocaleLowerCase();
    return (q ? locations.filter((item) => item.name.toLocaleLowerCase().includes(q)) : locations).slice(0, 8);
  }, [locations, search]);

  const selectProvince = useCallback((code: string, forecastId?: string) => {
    setDashboard({ selectedProvince: code, selectedForecastId: forecastId || "" });
  }, [setDashboard]);

  const selectAlert = (alert: Alert) => {
    selectProvince(alert.province_code, alert.forecast_id);
    setSidebarOpen(false);
  };

  const openAssistant = () => {
    if (window.innerWidth < 768) router.push("/assistant");
    else setCopilotOpen(true);
  };

  if (metadata.isLoading) return <Loading />;
  if (metadata.isError || !metadata.data) return <ErrorState />;

  return (
    <div className="map-workspace relative h-dvh w-full overflow-hidden bg-slate-100 text-slate-900">
      <div className="absolute inset-0">
        <IndonesiaMap geojson={geojson.data} layer={state.layer} selectedProvince={state.selectedProvince} onSelect={selectProvince} />
      </div>

      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-start justify-between gap-2 p-3 sm:p-4">
        <div className="pointer-events-auto flex items-center gap-2">
          <button onClick={() => setSidebarOpen(true)} aria-label="Open filters and alerts" className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-800 shadow-sm transition hover:bg-slate-50"><Menu size={20} /></button>
          <div className="hidden rounded-xl border border-slate-200 bg-white px-3.5 py-2 shadow-sm sm:block">
            <div className="text-sm font-bold tracking-tight text-slate-950">PasarPulse</div>
            <div className="text-[10px] font-medium text-slate-500">Food price early warning</div>
          </div>
        </div>

        <div className="pointer-events-auto flex min-w-0 items-start gap-2">
          <div className="relative">
            <button onClick={() => setCalendarOpen((value) => !value)} className="flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50">
              <CalendarDays size={17} className="text-slate-500" />
              <span className="hidden sm:inline">{dateLabel(state.origin || metadata.data.latest_origin || "")}</span>
            </button>
            {calendarOpen && (
              <div className="absolute right-0 mt-2 w-[300px]">
                <DatePicker value={state.origin || metadata.data.latest_origin || ""} dates={metadata.data.forecast_origins} onChange={(origin) => { setDashboard({ origin }); setCalendarOpen(false); }} />
              </div>
            )}
          </div>

          <div className="relative w-[min(52vw,330px)] sm:w-[330px]">
            <div className="flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 shadow-sm focus-within:border-slate-400 focus-within:ring-2 focus-within:ring-slate-100">
              <Search size={17} className="shrink-0 text-slate-400" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} onFocus={() => setSearchFocused(true)} onBlur={() => window.setTimeout(() => setSearchFocused(false), 120)} placeholder="Search location" className="min-w-0 flex-1 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400" />
              {search && <button onClick={() => setSearch("")} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X size={14} /></button>}
            </div>
            {searchFocused && filteredLocations.length > 0 && (
              <div className="absolute right-0 mt-2 w-full overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
                {filteredLocations.map((item) => <button key={item.code} onMouseDown={() => { selectProvince(item.code); setSearch(item.name); setSearchFocused(false); }} className="block w-full px-3 py-2.5 text-left text-sm text-slate-700 transition hover:bg-slate-50"><span className="font-medium text-slate-900">{item.name}</span><span className="ml-2 text-xs text-slate-400">Province</span></button>)}
              </div>
            )}
          </div>
        </div>
      </div>

      {sidebarOpen && <Sidebar metadata={metadata.data} alerts={alerts.data || []} onClose={() => setSidebarOpen(false)} onAlert={selectAlert} />}
      {selectedForCard && <RegionCard forecast={selectedForCard} onClose={() => setDashboard({ selectedProvince: "", selectedForecastId: "" })} />}

      <button onClick={openAssistant} className="absolute bottom-4 right-4 z-40 flex h-12 items-center gap-2 rounded-full bg-slate-950 px-4 text-sm font-semibold text-white shadow-xl transition hover:bg-slate-800 sm:bottom-5 sm:right-5" aria-label="Open PasarPulse AI">
        <MessageCircle size={18} /><span className="hidden sm:inline">Ask AI</span>
      </button>

      <CopilotPanel forecast={selected} />
    </div>
  );
}

function Sidebar({ metadata, alerts, onClose, onAlert }: { metadata: Metadata; alerts: Alert[]; onClose: () => void; onAlert: (alert: Alert) => void }) {
  return (
    <div className="fixed inset-0 z-[60] sm:pointer-events-none">
      <button aria-label="Close sidebar" onClick={onClose} className="absolute inset-0 hidden bg-slate-950/10 sm:block sm:pointer-events-auto" />
      <aside className="pointer-events-auto relative flex h-dvh w-full flex-col border-r border-slate-200 bg-white shadow-2xl sm:w-[390px]">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5">
          <div><div className="text-sm font-bold text-slate-950">PasarPulse</div><div className="text-xs text-slate-500">Map controls and urgent alerts</div></div>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"><X size={18} /></button>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto">
          <section className="border-b border-slate-200 p-4">
            <div className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[.1em] text-slate-500"><SlidersHorizontal size={14} /> Filters</div>
            <FilterBar metadata={metadata} />
          </section>
          <section className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[.1em] text-slate-500"><Bell size={14} /> Urgent alerts</div>
              <span className="text-[11px] text-slate-400">Top 10</span>
            </div>
            <div className="space-y-2">
              {alerts.slice(0, 10).map((alert, index) => <AlertRow key={alert.alert_id} alert={alert} index={index + 1} onClick={() => onAlert(alert)} />)}
              {alerts.length === 0 && <div className="rounded-xl border border-dashed border-slate-200 px-3 py-8 text-center text-sm text-slate-400">No alerts match these filters.</div>}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}

function AlertRow({ alert, index, onClick }: { alert: Alert; index: number; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left transition hover:border-slate-300 hover:bg-slate-50">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-500">{index}</span>
      <span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="truncate text-sm font-semibold text-slate-900">{alert.province_name}</span><RiskBadge level={alert.warning_level} /></span><span className="mt-1 block text-xs text-slate-500">{alert.commodity_name} · {signedPct(alert.projected_change_pct)}</span></span>
    </button>
  );
}

function RegionCard({ forecast, onClose }: { forecast: Forecast; onClose: () => void }) {
  const forecastXai = useQuery({ queryKey: ["forecast-xai", forecast.forecast_id], queryFn: () => api.forecastXai(forecast.forecast_id), retry: false });
  return (
    <div className="absolute bottom-20 left-3 right-3 z-30 rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-xl backdrop-blur sm:bottom-20 sm:left-auto sm:right-5 sm:w-[350px]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0"><div className="flex items-center gap-2"><h2 className="truncate text-base font-bold text-slate-950">{forecast.province_name}</h2><RiskBadge level={forecast.warning_level} /></div><p className="mt-1 text-xs text-slate-500">{forecast.commodity_name} · {forecast.market_level} · {forecast.horizon_days}-day forecast</p></div>
        <button onClick={onClose} className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-800"><X size={15} /></button>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <Stat label="Current" value={rupiah(forecast.current_price)} />
        <Stat label="Forecast" value={rupiah(forecast.predicted_price)} />
        <Stat label="Change" value={signedPct(forecast.projected_change_pct)} />
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3 text-[11px] text-slate-500"><span>Target {dateLabel(forecast.target_date)}</span><span>{forecast.evidence_status.replaceAll("_", " ").toLowerCase()}</span></div>
      {forecastXai.data && <ForecastXaiCard xai={forecastXai.data} />}
    </div>
  );
}

function ForecastXaiCard({ xai }: { xai: ForecastXai }) {
  return (
    <section className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-2.5">
      <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-[.08em] text-slate-500">XAI analysis · top 5 factors</div>
      <ol className="space-y-1">{xai.drivers.map((driver) => <li key={driver.rank} className="flex items-center justify-between gap-3 text-[10px]"><span className="min-w-0 truncate text-slate-600"><span className="mr-1 text-slate-400">{driver.rank}.</span>{featureLabel(driver.feature)}</span><span className={`shrink-0 font-mono ${driver.contribution_logratio >= 0 ? "text-emerald-700" : "text-rose-700"}`}>{signedContribution(driver.contribution_logratio)}</span></li>)}</ol>
    </section>
  );
}

function DatePicker({ value, dates, onChange }: { value: string; dates: string[]; onChange: (value: string) => void }) {
  const dateMap = useMemo(() => new Map(dates.map((item) => [item.slice(0, 10), item])), [dates]);
  const selectedKey = value.slice(0, 10);
  const selectedDate = parseDay(selectedKey || dates.at(-1)?.slice(0, 10) || new Date().toISOString().slice(0, 10));
  const [month, setMonth] = useState(() => new Date(Date.UTC(selectedDate.getUTCFullYear(), selectedDate.getUTCMonth(), 1)));

  useEffect(() => {
    const next = parseDay(selectedKey || dates.at(-1)?.slice(0, 10) || new Date().toISOString().slice(0, 10));
    setMonth(new Date(Date.UTC(next.getUTCFullYear(), next.getUTCMonth(), 1)));
  }, [dates, selectedKey]);

  const year = month.getUTCFullYear();
  const monthIndex = month.getUTCMonth();
  const firstDay = (new Date(Date.UTC(year, monthIndex, 1)).getUTCDay() + 6) % 7;
  const dayCount = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const cells = Array.from({ length: firstDay + dayCount }, (_, index) => index < firstDay ? null : index - firstDay + 1);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-xl">
      <div className="mb-3 flex items-center justify-between">
        <button onClick={() => setMonth(new Date(Date.UTC(year, monthIndex - 1, 1)))} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><ChevronLeft size={16} /></button>
        <div className="text-sm font-semibold text-slate-900">{new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" }).format(month)}</div>
        <button onClick={() => setMonth(new Date(Date.UTC(year, monthIndex + 1, 1)))} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><ChevronRight size={16} /></button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-semibold uppercase text-slate-400">{["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((day) => <div key={day} className="py-1">{day}</div>)}</div>
      <div className="mt-1 grid grid-cols-7 gap-1">
        {cells.map((day, index) => {
          if (!day) return <div key={`blank-${index}`} className="h-8" />;
          const key = `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
          const origin = dateMap.get(key);
          const active = key === selectedKey;
          return <button key={key} disabled={!origin} onClick={() => origin && onChange(origin)} className={`h-8 rounded-lg text-xs font-medium transition ${active ? "bg-slate-900 text-white" : origin ? "text-slate-700 hover:bg-slate-100" : "cursor-not-allowed text-slate-300"}`}>{day}</button>;
        })}
      </div>
      <div className="mt-3 border-t border-slate-100 pt-2 text-[10px] text-slate-400">Unavailable replay dates are disabled.</div>
    </div>
  );
}

function RiskBadge({ level }: { level: Forecast["warning_level"] }) {
  const className = level === "HIGH" ? "bg-red-50 text-red-700" : level === "ELEVATED" ? "bg-orange-50 text-orange-700" : level === "WATCH" ? "bg-yellow-50 text-yellow-700" : level === "STABLE" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600";
  return <span className={`shrink-0 rounded-full px-2 py-1 text-[9px] font-bold tracking-[.07em] ${className}`}>{level}</span>;
}
function Stat({ label, value }: { label: string; value: string }) { return <div className="rounded-xl bg-slate-50 px-2.5 py-2"><div className="text-[9px] font-semibold uppercase tracking-[.08em] text-slate-400">{label}</div><div className="mt-1 truncate text-xs font-bold text-slate-800">{value}</div></div>; }
function rupiah(value: number) { return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0, notation: value >= 100000 ? "compact" : "standard" }).format(value); }
function signedPct(value: number) { return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`; }
function signedContribution(value: number) { return `${value >= 0 ? "+" : ""}${value.toFixed(4)}`; }
function featureLabel(value: string) { return value.replaceAll("_", " "); }
function parseDay(value: string) { const [year, month, day] = value.split("-").map(Number); return new Date(Date.UTC(year || 1970, (month || 1) - 1, day || 1)); }
function dateLabel(value: string) { if (!value) return "Select date"; return new Intl.DateTimeFormat("en", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(parseDay(value.slice(0, 10))); }
function Loading() { return <div className="flex h-dvh items-center justify-center bg-white text-sm text-slate-500">Loading PasarPulse map…</div>; }
function ErrorState() { return <div className="flex h-dvh items-center justify-center bg-slate-50 p-6"><div className="max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm"><div className="text-base font-semibold text-slate-900">Forecast map unavailable</div><p className="mt-2 text-sm leading-relaxed text-slate-500">PasarPulse could not reach the forecast API. Start the FastAPI service and reload this page.</p></div></div>; }
