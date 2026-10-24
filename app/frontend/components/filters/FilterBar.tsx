"use client";
import type { Metadata } from "@/lib/types";
import { useDashboardStore } from "@/stores/dashboard";
import { shortDate } from "@/components/common/format";
const marketLabels: Record<string, string> = {
  producer: "Produsen",
  wholesale: "Pedagang besar",
  retail: "Eceran",
};
export function FilterBar({ metadata }: { metadata: Metadata }) {
  const state = useDashboardStore();
  return (
    <section className="filters" aria-label="Filter proyeksi">
      <label className="filter-field">
        <span>Komoditas</span>
        <select
          id="commodity-filter"
          value={state.commodity}
          onChange={(e) => state.set({ commodity: e.target.value })}
        >
          {metadata.commodities.map((item) => (
            <option key={item.code} value={item.code}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className="filter-field">
        <span>Pasar</span>
        <select
          id="market-filter"
          value={state.marketLevel}
          onChange={(e) => state.set({ marketLevel: e.target.value })}
        >
          {metadata.market_levels.map((item) => (
            <option key={item} value={item}>
              {marketLabels[item] || item}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="filter-field horizon-field">
        <legend>Horizon</legend>
        <div className="segmented" aria-label="Horizon proyeksi">
          {metadata.horizons.map((days) => (
            <button
              key={days}
              aria-pressed={state.horizon === days}
              onClick={() => state.set({ horizon: days })}
            >
              {days} hari
            </button>
          ))}
        </div>
      </fieldset>
      <label className="filter-field">
        <span>Snapshot</span>
        <select
          id="origin-filter"
          value={state.origin || metadata.latest_origin || ""}
          onChange={(e) => state.set({ origin: e.target.value })}
        >
          {metadata.forecast_origins.map((date) => (
            <option key={date} value={date}>
              {shortDate(date)}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}
