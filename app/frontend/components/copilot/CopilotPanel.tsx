"use client";

import { useState } from "react";
import { Bot, CornerDownLeft, Loader2, MapPin, X } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { CopilotResult, Evidence, Forecast } from "@/lib/types";
import { shortDate } from "@/components/common/format";
import { useDashboardStore } from "@/stores/dashboard";
import { isAllowedDashboardAction } from "@/lib/actions";

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  mode?: string;
  reasons?: CopilotResult["reasons"];
  actions?: CopilotResult["actions"];
};

export function CopilotPanel({ forecast, standalone = false }: { forecast?: Forecast; standalone?: boolean }) {
  const router = useRouter();
  const open = useDashboardStore((state) => state.copilotOpen);
  const set = useDashboardStore((state) => state.set);
  const setCopilotOpen = useDashboardStore((state) => state.setCopilotOpen);
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const evidence = useQuery({
    queryKey: ["copilot-evidence", forecast?.forecast_id],
    queryFn: () => api.evidence(forecast!.forecast_id),
    enabled: Boolean(forecast?.forecast_id),
  });
  const suggestions = buildSuggestions(forecast, evidence.data);

  const mutation = useMutation({
    mutationFn: (value: string) => api.copilot(value, {
      province_code: forecast?.province_code,
      province_name: forecast?.province_name,
      commodity_code: forecast?.commodity_code,
      commodity_name: forecast?.commodity_name,
      market_level: forecast?.market_level,
      horizon_days: forecast?.horizon_days,
      forecast_origin: forecast?.forecast_origin,
    }),
    onSuccess: (result, value) => {
      setHistory((items) => [
        ...items,
        { role: "user", text: value },
        { role: "assistant", text: result.summary, mode: result.mode, reasons: result.reasons, actions: result.actions },
      ]);
      setMessage("");
      const actionMap: Record<string, string> = { SET_COMMODITY: "commodity", SET_MARKET_LEVEL: "marketLevel", SET_HORIZON: "horizon", SET_MAP_LAYER: "layer", SET_REPLAY_ORIGIN: "origin", SET_PROVINCE: "selectedProvince" };
      result.dashboard_actions.filter(isAllowedDashboardAction).forEach((action) => {
        const key = actionMap[action.type];
        if (key) set({ [key]: action.value } as never);
      });
    },
  });

  if (!standalone && !open) return null;
  const send = (value = message) => { if (value.trim()) mutation.mutate(value.trim()); };
  const close = () => standalone ? router.push("/") : setCopilotOpen(false);
  const shellClass = standalone
    ? "relative flex h-dvh w-full flex-col bg-white"
    : "fixed inset-y-0 right-0 z-[70] flex w-full flex-col border-l border-slate-200 bg-white shadow-2xl md:max-w-[440px]";

  return (
    <aside className={shellClass}>
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5 sm:px-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-white"><Bot size={17} /></div>
          <div><div className="text-sm font-semibold text-slate-950">PasarPulse AI</div><div className="text-[11px] text-slate-500">Grounded in the selected forecast</div></div>
        </div>
        <button onClick={close} aria-label="Close assistant" className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"><X size={18} /></button>
      </div>

      {forecast && (
        <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 sm:px-5">
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[.1em] text-slate-500"><MapPin size={12} /> Current region</div>
          <div className="flex items-start justify-between gap-4">
            <div><div className="font-semibold text-slate-950">{forecast.province_name}</div><div className="mt-0.5 text-xs text-slate-500">{forecast.commodity_name} · {forecast.market_level} · {forecast.horizon_days} days</div></div>
            <RiskBadge level={forecast.warning_level} />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Metric label="Current" value={rupiah(forecast.current_price)} />
            <Metric label="Forecast" value={rupiah(forecast.predicted_price)} />
            <Metric label="Change" value={`${forecast.projected_change_pct >= 0 ? "+" : ""}${forecast.projected_change_pct.toFixed(1)}%`} />
          </div>
        </div>
      )}

      <div className="scrollbar-thin flex-1 space-y-3 overflow-y-auto px-4 py-4 sm:px-5">
        {history.length === 0 && (
          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[.1em] text-slate-500">Ask about the loaded evidence</div>
            <div className="space-y-2">
              {suggestions.map((item) => <button key={item} onClick={() => send(item)} className="block w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-sm text-slate-700 transition hover:border-slate-400 hover:bg-slate-50">{item}</button>)}
            </div>
            {evidence.isLoading && <div className="mt-3 text-xs text-slate-400">Loading forecast-specific evidence…</div>}
            <p className="mt-4 text-xs leading-relaxed text-slate-500">Answers are retrieved from the selected forecast and modality snapshot. Feature-contract inclusion is not model attribution; unsupported probabilities and confidence values remain unavailable.</p>
          </div>
        )}
        {history.map((item, index) => (
          <div key={`${item.role}-${index}`} className={item.role === "user" ? "ml-8 rounded-2xl bg-slate-900 px-3.5 py-2.5 text-sm text-white" : "rounded-2xl border border-slate-200 bg-white px-3.5 py-3 text-sm leading-relaxed text-slate-700 shadow-sm"}>
            <div>{item.text}</div>
            {item.role === "assistant" && item.reasons && item.reasons.length > 0 && (
              <div className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-xs text-slate-600">
                <div className="font-semibold uppercase tracking-[.1em] text-slate-400">Evidence trace</div>
                {item.reasons.slice(0, 4).map((reason, reasonIndex) => <div key={`${reasonIndex}-${reason.text}`}><div>{reason.text}</div>{reason.evidence_ids.length > 0 && <div className="mt-0.5 font-mono text-[10px] text-slate-400">{reason.evidence_ids.join(" · ")}</div>}</div>)}
              </div>
            )}
            {item.role === "assistant" && item.actions && item.actions.length > 0 && <div className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500"><span className="font-semibold uppercase tracking-[.1em] text-slate-400">Approved analyst actions:</span> {item.actions.map((action) => action.action_id).join(" · ")}</div>}
            {item.role === "assistant" && forecast && <div className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">Relevant view: {forecast.province_name}, {forecast.commodity_name}, forecast origin {shortDate(forecast.forecast_origin)}.</div>}
            {item.mode && <div className="mt-2 text-[10px] uppercase tracking-[.1em] text-slate-400">{item.mode}</div>}
          </div>
        ))}
        {mutation.isError && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700"><div className="font-semibold">Copilot request failed.</div><div className="mt-1">{mutation.error instanceof Error ? mutation.error.message : "No grounded answer was returned."}</div><div className="mt-2 text-xs text-red-600">No fallback answer was generated.</div></div>}
        {mutation.isPending && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Checking structured evidence…</div>}
      </div>

      <div className="border-t border-slate-200 bg-white px-4 py-3 sm:px-5 sm:py-4">
        <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-slate-500 focus-within:ring-2 focus-within:ring-slate-100">
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } }} rows={2} placeholder="Ask about prices, risk, evidence, or regions…" className="min-h-[44px] flex-1 resize-none bg-transparent px-2 py-1 text-sm text-slate-900 outline-none placeholder:text-slate-400" />
          <button onClick={() => send()} disabled={mutation.isPending || !message.trim()} aria-label="Send" className="rounded-xl bg-slate-900 p-2.5 text-white disabled:cursor-not-allowed disabled:opacity-35"><CornerDownLeft size={16} /></button>
        </div>
      </div>
    </aside>
  );
}

function buildSuggestions(forecast: Forecast | undefined, evidence: Evidence | undefined): string[] {
  const province = forecast?.province_name || "this province";
  const level = forecast?.warning_level?.toLowerCase() || "this warning";
  const items = evidence?.items || [];
  const suggestions = [
    `Why is ${province} ${level}?`,
    evidence && items.some((item) => item.available && item.modality === "Weather") ? "What weather evidence is available here?" : "Which evidence sources are missing or stale?",
    evidence && items.some((item) => item.available && item.modality === "Satellite") ? "What does the satellite context show?" : "Which modalities are in the selected model?",
    evidence?.model_feature_contract ? `What does the ${evidence.model_feature_contract} model contract use?` : "Which provinces have the highest loaded risk?",
  ];
  return Array.from(new Set(suggestions)).slice(0, 4);
}

function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg border border-slate-200 bg-white px-2.5 py-2"><div className="text-[10px] uppercase tracking-[.08em] text-slate-400">{label}</div><div className="mt-0.5 truncate text-xs font-semibold text-slate-800">{value}</div></div>; }
function RiskBadge({ level }: { level: Forecast["warning_level"] }) { const className = level === "HIGH" ? "bg-red-50 text-red-700" : level === "ELEVATED" ? "bg-orange-50 text-orange-700" : level === "WATCH" ? "bg-yellow-50 text-yellow-700" : level === "STABLE" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"; return <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold tracking-[.08em] ${className}`}>{level}</span>; }
function rupiah(value: number) { return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(value); }
