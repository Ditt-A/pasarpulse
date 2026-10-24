"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { ArrowRight, GitCompareArrows, Info } from "lucide-react";
import { api } from "@/lib/api";
import type { Forecast } from "@/lib/types";
import { rankForecasts } from "@/lib/overview.mjs";
import { useForecastContext } from "@/lib/useForecastContext";
import { idr, pct, shortDate } from "@/components/common/format";
import { StatusBadge } from "@/components/common/StatusBadge";
import { FilterBar } from "@/components/filters/FilterBar";
import { RequestState } from "@/components/common/RequestState";
const Chart = dynamic(() => import("echarts-for-react"), { ssr: false });
export default function IntelligencePage() {
  const { state, metadata, ready, params } = useForecastContext();
  const [second, setSecond] = useState("32");
  const forecasts = useQuery({
    queryKey: ["forecasts", params],
    queryFn: () => api.forecasts(params),
    enabled: ready,
  });
  const ranked = useMemo(
    () => rankForecasts(forecasts.data || []),
    [forecasts.data],
  );
  const firstCode = state.selectedProvince || ranked[0]?.province_code || "";
  const secondCode = ranked.some(
    (x) => x.province_code === second && x.province_code !== firstCode,
  )
    ? second
    : ranked.find((x) => x.province_code !== firstCode)?.province_code || "";
  const first = ranked.find((x) => x.province_code === firstCode);
  const comparison = ranked.find((x) => x.province_code === secondCode);
  if (metadata.isError)
    return <RequestState error retry={() => void metadata.refetch()} />;
  if (!metadata.data) return <RequestState />;
  const chart = {
    color: ["#a9bf9b", "#285c45"],
    grid: { top: 40, right: 30, bottom: 20, left: 20, containLabel: true },
    legend: {
      data: ["Current price", "Forecast"],
      right: 20,
      top: 0,
      icon: "roundRect",
      textStyle: { color: "#71816a", fontSize: 11 },
    },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => `${idr(v)}/kg` },
    xAxis: {
      type: "category",
      data: [first?.province_name, comparison?.province_name],
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#dfe6dd" } },
      axisLabel: { color: "#5a7150", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: "#7b8973",
        fontSize: 10,
        formatter: (v: number) => `${Math.round(v / 1000)}k`,
      },
      splitLine: { lineStyle: { color: "#e9eee4", type: "dashed" } },
    },
    series: [
      {
        name: "Current price",
        type: "bar",
        barMaxWidth: 36,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        data: [first?.current_price, comparison?.current_price],
      },
      {
        name: "Forecast",
        type: "bar",
        barMaxWidth: 36,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
        data: [first?.predicted_price, comparison?.predicted_price],
      },
    ],
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">Compare markets</div>
          <h1>Regional intelligence</h1>
          <p>
            Two provinces. The same commodity, market level, and forecast date.
          </p>
        </div>
        <GitCompareArrows
          size={25}
          strokeWidth={1.4}
          className="hidden text-[#718969] sm:block"
        />
      </div>
      <FilterBar metadata={metadata.data} />
      {forecasts.isError ? (
        <RequestState error retry={() => void forecasts.refetch()} />
      ) : !ready || forecasts.isPending ? (
        <RequestState />
      ) : !ranked.length ? (
        <div className="surface empty-state">
          No forecasts match the selected context.
        </div>
      ) : (
        <>
          <div className="grid gap-5 md:grid-cols-2">
            <CompareCard
              title="Selected province"
              forecast={first}
              value={firstCode}
              onChange={(value) => state.set({ selectedProvince: value })}
              options={ranked}
            />
            <CompareCard
              title="Compare against"
              forecast={comparison}
              value={secondCode}
              onChange={setSecond}
              options={ranked.filter((x) => x.province_code !== firstCode)}
            />
          </div>
          {first && comparison && (
            <section className="surface mt-5">
              <div className="surface-heading">
                <div>
                  <h2>Current and projected prices</h2>
                  <p>
                    IDR per kilogram · {state.horizon}-day horizon · As of{" "}
                    {shortDate(state.origin)}
                  </p>
                </div>
              </div>
              <div className="p-4">
                <Chart option={chart} style={{ height: 280 }} />
              </div>
            </section>
          )}
          <section className="surface mt-5">
            <div className="surface-heading">
              <div>
                <h2>Regional ranking</h2>
                <p>Highest projected changes in this snapshot</p>
              </div>
            </div>
            <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-3">
              {ranked.slice(0, 12).map((row, i) => (
                <button
                  key={row.forecast_id}
                  onClick={() =>
                    state.set({ selectedProvince: row.province_code })
                  }
                  className="flex items-center justify-between gap-3 rounded-md border border-line p-4 text-left transition hover:bg-sage"
                >
                  <span className="flex items-center gap-3">
                    <span className="text-[10px] text-[#94a48b]">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-xs font-medium">
                      {row.province_name}
                    </span>
                  </span>
                  <span
                    className={`text-xs ${row.projected_change_pct > 0 ? "change-up" : "change-down"}`}
                  >
                    {pct(row.projected_change_pct)}
                  </span>
                </button>
              ))}
            </div>
          </section>
        </>
      )}
      <div className="notice mt-5">
        <Info size={15} />
        <span>
          Comparisons use forecast-time prices and saved predictions. Later
          realized prices are excluded from this ranking.
        </span>
      </div>
    </>
  );
}
function CompareCard({
  title,
  forecast,
  value,
  onChange,
  options,
}: {
  title: string;
  forecast?: Forecast;
  value: string;
  onChange: (value: string) => void;
  options: Forecast[];
}) {
  return (
    <section className="surface">
      <div className="border-b border-line p-5">
        <label className="text-[11px] text-[#71816a]">
          {title}
          <select
            className="mt-2 block w-full rounded-md border border-line bg-white p-2.5 text-sm font-medium text-[#304c36]"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          >
            {!options.some((x) => x.province_code === value) && (
              <option value={value}>No forecast for selected province</option>
            )}
            {[...options]
              .sort((a, b) => a.province_name.localeCompare(b.province_name))
              .map((row) => (
                <option key={row.province_code} value={row.province_code}>
                  {row.province_name}
                </option>
              ))}
          </select>
        </label>
      </div>
      {forecast ? (
        <div className="p-5">
          <div className="mb-5 flex items-center justify-between">
            <StatusBadge label={forecast.warning_level} />
            <span
              className={
                forecast.projected_change_pct > 0 ? "change-up" : "change-down"
              }
            >
              {pct(forecast.projected_change_pct)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[10px] text-[#71816a]">Current / kg</div>
              <strong className="mt-1 block text-xl font-medium tracking-[-.6px]">
                {idr(forecast.current_price)}
              </strong>
            </div>
            <ArrowRight size={16} className="text-[#9cae92]" />
            <div>
              <div className="text-[10px] text-[#71816a]">Forecast / kg</div>
              <strong className="mt-1 block text-xl font-semibold tracking-[-.6px]">
                {idr(forecast.predicted_price)}
              </strong>
            </div>
          </div>
          <p className="mt-4 text-[10px] text-[#71816a]">
            As of {shortDate(forecast.forecast_origin)} · Target{" "}
            {shortDate(forecast.target_date)}
          </p>
        </div>
      ) : (
        <div className="empty-state text-xs">
          No forecast is available for this province. Choose another province.
        </div>
      )}
    </section>
  );
}
