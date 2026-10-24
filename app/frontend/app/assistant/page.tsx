"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { useDashboardStore } from "@/stores/dashboard";

export default function AssistantPage() {
  const state = useDashboardStore();
  const setDashboard = useDashboardStore((value) => value.set);
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });

  useEffect(() => {
    if (metadata.data?.latest_origin && !state.origin) setDashboard({ origin: metadata.data.latest_origin });
  }, [metadata.data?.latest_origin, setDashboard, state.origin]);

  const params = { origin: state.origin || metadata.data?.latest_origin || undefined, commodity: state.commodity, market_level: state.marketLevel, horizon: state.horizon };
  const forecasts = useQuery({ queryKey: ["forecasts", params], queryFn: () => api.forecasts(params), enabled: Boolean(metadata.data) });
  const selected = forecasts.data?.find((item) => item.province_code === state.selectedProvince) || forecasts.data?.[0];

  if (metadata.isLoading || forecasts.isLoading) return <div className="flex h-dvh items-center justify-center bg-white text-sm text-slate-500">Loading PasarPulse AI…</div>;
  return <CopilotPanel forecast={selected} standalone />;
}
