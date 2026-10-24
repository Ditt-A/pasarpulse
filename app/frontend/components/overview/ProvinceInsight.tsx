"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  Check,
  Clock3,
  Database,
  Eye,
  Info,
  MapPin,
} from "lucide-react";
import Link from "next/link";
import type { Forecast } from "@/lib/types";
import { api } from "@/lib/api";
import { idr, pct, shortDate } from "@/components/common/format";
import { StatusBadge } from "@/components/common/StatusBadge";
const Chart = dynamic(() => import("echarts-for-react"), { ssr: false });

export function ProvinceInsight({
  forecast,
  onClose,
}: {
  forecast: Forecast;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("forecast");
  const [reveal, setReveal] = useState(false);
  const evidence = useQuery({
    queryKey: ["evidence", forecast.forecast_id],
    queryFn: () => api.evidence(forecast.forecast_id),
    enabled: tab === "evidence",
  });
  const xai = useQuery({
    queryKey: ["forecast-xai", forecast.forecast_id],
    queryFn: () => api.forecastXai(forecast.forecast_id),
    retry: false,
  });
  const evaluation = useQuery({
    queryKey: ["forecast-evaluation", forecast.forecast_id],
    queryFn: () => api.forecast(forecast.forecast_id, true),
    enabled: reveal,
  });
  const tabs = [
    "forecast",
    "evidence",
    ...(xai.data?.drivers.length ? ["drivers"] : []),
  ];
  const rising = forecast.projected_change_pct > 0;
  const chart = {
    animationDuration: 450,
    animation:
      typeof window !== "undefined" &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    grid: { left: 6, right: 8, top: 22, bottom: 6, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#fff",
      borderColor: "#dfe6dd",
      textStyle: { color: "#20362b", fontSize: 11 },
      valueFormatter: (v: number) => `${idr(v)}/kg`,
    },
    xAxis: {
      type: "category",
      boundaryGap: true,
      data: [
        shortDate(forecast.forecast_origin),
        shortDate(forecast.target_date),
      ],
      axisLine: { lineStyle: { color: "#dfe6dd" } },
      axisTick: { show: false },
      axisLabel: { color: "#7a8a73", fontSize: 10 },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitNumber: 3,
      axisLabel: {
        formatter: (v: number) => `${Math.round(v / 1000)}k`,
        color: "#7a8a73",
        fontSize: 9,
      },
      splitLine: { lineStyle: { color: "#e9eee5", type: "dashed" } },
    },
    series: [
      {
        type: "line",
        data: [
          { value: forecast.current_price, itemStyle: { color: "#7c9b71" } },
          {
            value: forecast.predicted_price,
            itemStyle: { color: rising ? "#b34b3e" : "#285c45" },
          },
        ],
        smooth: false,
        symbolSize: 8,
        lineStyle: {
          color: rising ? "#b34b3e" : "#285c45",
          type: "dashed",
          width: 2,
        },
      },
    ],
  };
  return (
    <section
      id="province-insight"
      className="surface panel-enter province-insight"
      aria-label={`${forecast.province_name} forecast`}
    >
      <div className="px-5 pt-4 pb-3">
        <button className="ui-link text-[10px]" onClick={onClose}>
          <ArrowLeft size={12} />
          All provinces
        </button>
        <div className="mt-4 flex items-start justify-between gap-3">
          <div>
            <div className="eyebrow mb-2">Province outlook</div>
            <h2 className="text-xl font-semibold tracking-[-.5px]">
              {forecast.province_name}
            </h2>
          </div>
          <StatusBadge label={forecast.warning_level} />
        </div>
        <p className="mt-2 text-[11px] text-[#72806b]">
          {forecast.commodity_name} · {forecast.market_level}
        </p>
        <p className="mt-2 flex items-center gap-1.5 text-[10px] text-[#72806b]">
          <CalendarDays size={11} />
          As of {shortDate(forecast.forecast_origin)} · {forecast.horizon_days}{" "}
          days
        </p>
      </div>
      <div
        className="flex gap-5 border-b border-line px-5"
        role="tablist"
        aria-label="Forecast detail"
      >
        {tabs.map((item) => (
          <button
            key={item}
            id={`detail-tab-${item}`}
            role="tab"
            aria-selected={tab === item}
            aria-controls={`detail-panel-${forecast.forecast_id}`}
            tabIndex={tab === item ? 0 : -1}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                const next =
                  (tabs.indexOf(tab) +
                    (e.key === "ArrowRight" ? 1 : -1) +
                    tabs.length) %
                  tabs.length;
                setTab(tabs[next]);
                document.getElementById(`detail-tab-${tabs[next]}`)?.focus();
              }
            }}
            onClick={() => setTab(item)}
            className={`border-b-2 py-3 text-[11px] capitalize ${tab === item ? "border-cyanpulse font-semibold text-cyanpulse" : "border-transparent text-[#788570]"}`}
          >
            {item === "drivers" ? "Model drivers" : item}
          </button>
        ))}
      </div>
      <div
        id={`detail-panel-${forecast.forecast_id}`}
        role="tabpanel"
        aria-labelledby={`detail-tab-${tab}`}
        className="p-5"
      >
        {tab === "forecast" && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[10px] text-[#7a8772]">Current price / kg</p>
                <div className="mt-1 text-base font-medium tracking-[-.4px]">
                  {idr(forecast.current_price)}
                </div>
              </div>
              <div>
                <p className="text-[10px] text-[#7a8772]">
                  {forecast.horizon_days}-day forecast / kg
                </p>
                <div className="mt-1 text-base font-semibold tracking-[-.4px]">
                  {idr(forecast.predicted_price)}
                </div>
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <strong
                className={`text-2xl font-semibold tracking-[-.8px] ${rising ? "change-up" : "change-down"}`}
              >
                {pct(forecast.projected_change_pct)}
              </strong>
              <span className="text-[10px] text-[#7a8772]">
                projected movement
              </span>
            </div>
            <Chart option={chart} style={{ height: 145 }} />
            <p className="text-[9px] leading-relaxed text-[#7a8772]">
              Observed price → forecast endpoint. The dashed line connects two
              values; it is not a daily price trajectory.
            </p>
            <div className="mt-4 flex justify-between border-t border-line pt-3 text-[10px] text-[#718169]">
              <span>Target date</span>
              <strong className="font-medium text-[#385337]">
                {shortDate(forecast.target_date)}
              </strong>
            </div>
            {forecast.historical_evaluation.available && (
              <div className="mt-4 rounded-md bg-[#f7f6ee] p-3 text-[10px] leading-relaxed text-[#81734c]">
                <strong className="block font-semibold">
                  Historical evaluation only
                </strong>
                <p className="mt-1">
                  Outcomes recorded after the forecast date.
                </p>
                {!reveal ? (
                  <button
                    className="ui-link mt-2 text-[10px]"
                    onClick={() => setReveal(true)}
                  >
                    <Eye size={12} />
                    Reveal later outcome
                  </button>
                ) : evaluation.isPending ? (
                  <p className="mt-2">Loading historical outcome…</p>
                ) : evaluation.isError ? (
                  <button
                    className="ui-link mt-2 text-[10px]"
                    onClick={() => void evaluation.refetch()}
                  >
                    Retry historical outcome
                  </button>
                ) : (
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <div>
                      Realized later
                      <strong className="mt-1 block text-xs text-[#4b513f]">
                        {idr(
                          evaluation.data?.historical_evaluation.realized_price,
                        )}
                      </strong>
                    </div>
                    <div>
                      Absolute error
                      <strong className="mt-1 block text-xs text-[#4b513f]">
                        {idr(
                          evaluation.data?.historical_evaluation.absolute_error,
                        )}
                      </strong>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
        {tab === "evidence" && (
          <div className="space-y-3">
            {evidence.isPending ? (
              <p className="py-8 text-xs text-[#718169]">Loading evidence…</p>
            ) : evidence.isError ? (
              <div className="py-5 text-xs text-[#718169]">
                Evidence is temporarily unavailable.
                <button
                  className="ui-link mt-3 block"
                  onClick={() => void evidence.refetch()}
                >
                  Try again
                </button>
              </div>
            ) : (
              <>
                <p className="text-[11px] leading-relaxed text-[#718169]">
                  Availability and freshness describe the source data, not model
                  confidence.
                </p>
                {evidence.data?.items.map((item) => (
                  <div
                    key={item.evidence_id}
                    className="rounded-md border border-line p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium">
                        {item.modality}
                      </span>
                      {item.available ? (
                        <Check size={13} className="text-cyanpulse" />
                      ) : (
                        <span className="text-[9px] text-[#84917c]">
                          Unavailable
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex gap-2 text-[9px] text-[#7a8772]">
                      <span>
                        {item.used_by_model
                          ? "In model contract"
                          : "Context only"}
                      </span>
                      {item.observation_age_days != null && (
                        <span className="flex items-center gap-1">
                          <Clock3 size={10} />
                          {item.observation_age_days}d old
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-[10px] leading-relaxed text-[#718169]">
                      {item.note || item.source || "No source note available."}
                    </p>
                  </div>
                ))}
                <div className="flex gap-2 text-[10px] leading-relaxed text-[#718169]">
                  <Info size={13} className="shrink-0" />
                  Evidence availability is not a causal explanation.
                </div>
              </>
            )}
          </div>
        )}
        {tab === "drivers" && xai.data && (
          <div>
            <p className="mb-4 text-[11px] leading-relaxed text-[#718169]">
              Saved feature contributions to the model’s log-ratio output. These
              are predictive contributions, not causal effects.
            </p>
            {xai.data.drivers.map((driver) => (
              <div key={driver.rank} className="border-b border-line py-3">
                <div className="flex justify-between gap-3 text-[10px]">
                  <span className="min-w-0 break-words text-[#496040]">
                    {driver.feature.replaceAll("_", " ")}
                  </span>
                  <strong
                    className={
                      driver.contribution_logratio >= 0
                        ? "change-up"
                        : "change-down"
                    }
                  >
                    {driver.contribution_logratio >= 0 ? "+" : ""}
                    {driver.contribution_logratio.toFixed(4)}
                  </strong>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="panel-bottom">
        <Link className="ui-link text-[11px]" href="/intelligence">
          <MapPin size={12} />
          Compare regions <ArrowUpRight size={12} />
        </Link>
        <Database size={13} />
      </div>
    </section>
  );
}
