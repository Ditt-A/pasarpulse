"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Info } from "lucide-react";
import { api } from "@/lib/api";
import { useForecastContext } from "@/lib/useForecastContext";
import { FilterBar } from "@/components/filters/FilterBar";
import { AlertQueue } from "@/components/alerts/AlertQueue";
import { RequestState } from "@/components/common/RequestState";
import { shortDate } from "@/components/common/format";
export default function AlertsPage() {
  const { state, metadata, ready, params } = useForecastContext();
  const [risk, setRisk] = useState("ALL");
  const router = useRouter();
  const alerts = useQuery({
    queryKey: ["alerts-page", params, risk],
    queryFn: () =>
      api.alerts({
        ...params,
        risk: risk === "ALL" ? undefined : risk,
        limit: 500,
      }),
    enabled: ready,
  });
  if (metadata.isError)
    return <RequestState error retry={() => void metadata.refetch()} />;
  if (!metadata.data) return <RequestState />;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">Monitoring priorities</div>
          <h1>Alert queue</h1>
          <p>
            Review projected price increases and decide where to look closer.
          </p>
        </div>
        <span className="hidden text-xs text-[#72816a] sm:block">
          As of {shortDate(state.origin)}
        </span>
      </div>
      <FilterBar metadata={metadata.data} />
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="table-tabs" aria-label="Alert warning level">
          {["ALL", "HIGH", "ELEVATED", "WATCH", "STABLE"].map((level) => (
            <button
              key={level}
              onClick={() => setRisk(level)}
              aria-pressed={risk === level}
            >
              {level === "ALL"
                ? "All warnings"
                : level.charAt(0) + level.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
        <span className="text-[11px] text-[#72816a]">
          {alerts.data?.length ?? "—"} matching forecasts
        </span>
      </div>
      {alerts.isError ? (
        <RequestState error retry={() => void alerts.refetch()} />
      ) : !ready || alerts.isPending ? (
        <RequestState />
      ) : (
        <AlertQueue
          alerts={alerts.data}
          onSelect={(alert) => {
            state.set({
              selectedProvince: alert.province_code,
              selectedForecastId: alert.forecast_id,
            });
            router.push("/");
          }}
        />
      )}
      <div className="notice mt-5">
        <Info size={15} />
        <span>
          Warning levels are configurable review thresholds over projected
          positive price movement. They are not model probabilities or automatic
          intervention instructions.
        </span>
      </div>
    </>
  );
}
