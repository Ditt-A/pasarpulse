"use client";

import type { Metadata } from "@/lib/types";
import { useDashboardStore } from "@/stores/dashboard";

const selectClass = "mt-1.5 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium normal-case tracking-normal text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100";
const labelClass = "block text-[11px] font-semibold uppercase tracking-[.11em] text-slate-500";

export function FilterBar({ metadata }: { metadata: Metadata }) {
  const state = useDashboardStore();

  return (
    <div className="space-y-4">
      <label className={labelClass}>
        Commodity
        <select value={state.commodity} onChange={(event) => state.set({ commodity: event.target.value })} className={selectClass}>
          {metadata.commodities.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
        </select>
      </label>
      <label className={labelClass}>
        Market level
        <select value={state.marketLevel} onChange={(event) => state.set({ marketLevel: event.target.value })} className={selectClass}>
          {metadata.market_levels.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className={labelClass}>
        Horizon
        <select value={state.horizon} onChange={(event) => state.set({ horizon: Number(event.target.value) })} className={selectClass}>
          {metadata.horizons.map((item) => <option key={item} value={item}>{item} days</option>)}
        </select>
      </label>
      <label className={labelClass}>
        Forecast origin
        <select value={state.origin || metadata.latest_origin || ""} onChange={(event) => state.set({ origin: event.target.value })} className={selectClass}>
          {metadata.forecast_origins.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <label className={labelClass}>
        Map layer
        <select value={state.layer} onChange={(event) => state.set({ layer: event.target.value })} className={selectClass}>
          <option value="risk">Projected price-shock risk</option>
          <option value="change">Projected change %</option>
          <option value="evidence">Evidence availability</option>
        </select>
      </label>
    </div>
  );
}
