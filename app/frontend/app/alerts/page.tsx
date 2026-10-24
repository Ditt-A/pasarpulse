"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Filter, ListFilter } from "lucide-react";
import { api } from "@/lib/api";
import { useDashboardStore } from "@/stores/dashboard";
import { FilterBar } from "@/components/filters/FilterBar";
import { AlertQueue } from "@/components/alerts/AlertQueue";
import { Panel } from "@/components/common/Panel";
import { StatusBadge } from "@/components/common/StatusBadge";

export default function AlertsPage() {
  const state = useDashboardStore(); const [risk, setRisk] = useState("ALL");
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  useEffect(() => { if (metadata.data?.latest_origin && !state.origin) state.set({ origin: metadata.data.latest_origin }); }, [metadata.data?.latest_origin, state]);
  const params = { origin: state.origin || undefined, commodity: state.commodity, market_level: state.marketLevel, horizon: state.horizon, risk: risk === "ALL" ? undefined : risk, limit: 500 };
  const alerts = useQuery({ queryKey: ["alerts-page", params], queryFn: () => api.alerts(params), enabled: Boolean(metadata.data) });
  if (!metadata.data) return <Panel title="Alerts" eyebrow="Analyst work queue"><div className="p-8 text-sm text-slate-500">Loading alert metadata…</div></Panel>;
  return <div className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="mb-2 flex items-center gap-3"><h1 className="text-2xl font-semibold text-white">Alerts</h1><StatusBadge label={metadata.data.mode_label} /></div><p className="text-sm text-slate-400">A ranked work queue for verification and human review. Severity is a transparent product warning rule over the selected forecast.</p></div><div className="flex items-center gap-2 text-xs text-slate-500"><ListFilter size={15} /> {alerts.data?.length || 0} matching alerts</div></div><FilterBar metadata={metadata.data} /><div className="flex flex-wrap gap-2"><Filter size={15} className="mt-2 text-slate-500" />{["ALL", "HIGH", "ELEVATED", "WATCH", "STABLE"].map((item) => <button key={item} onClick={() => setRisk(item)} className={`rounded-lg border px-3 py-2 text-[10px] font-bold tracking-[.1em] ${risk === item ? "border-cyanpulse/50 bg-cyanpulse/10 text-cyanpulse" : "border-line text-slate-500"}`}>{item}</button>)}</div><AlertQueue alerts={alerts.data || []} /></div>;
}
