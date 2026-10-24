"use client";
import type { Metadata } from "@/lib/types";
import { useDashboardStore } from "@/stores/dashboard";
import { shortDate } from "@/components/common/format";
const marketLabels: Record<string, string> = {
  producer: "Producer market",
  wholesale: "Wholesale market",
  retail: "Retail market",
};
export function FilterBar({ metadata }: { metadata: Metadata }) {
  const state = useDashboardStore();
  return (
    <section className="filters" aria-label="Forecast filters">
      <div className="filter-field">
        <label htmlFor="commodity-filter">Commodity</label>
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
      </div>
      <div className="filter-field">
        <label htmlFor="market-filter">Market level</label>
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
      </div>
      <fieldset className="filter-field">
        <legend>Forecast horizon</legend>
        <div className="segmented" aria-label="Forecast horizon">
          {metadata.horizons.map((item) => (
            <button
              key={item}
              onClick={() => state.set({ horizon: item })}
              aria-pressed={state.horizon === item}
            >
              {item} days
            </button>
          ))}
        </div>
      </fieldset>
      <div className="filter-field">
        <label htmlFor="origin-filter">Forecast as of</label>
        <select
          id="origin-filter"
          value={state.origin || metadata.latest_origin || ""}
          onChange={(e) => state.set({ origin: e.target.value })}
        >
          {metadata.forecast_origins.map((item) => (
            <option key={item} value={item}>
              {shortDate(item)}
            </option>
          ))}
        </select>
      </div>
    </section>
  );
}
