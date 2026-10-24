"use client";

import { CheckCircle2, CircleDashed, FlaskConical, LockKeyhole } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Panel } from "@/components/common/Panel";
import { StatusBadge } from "@/components/common/StatusBadge";
import { idr } from "@/components/common/format";

export default function ModelPage() {
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  const benchmarks = useQuery({ queryKey: ["benchmarks"], queryFn: api.benchmarks });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-white">Model & research lineage</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">A reviewer-facing view of what is evaluated, what is loaded for replay, and what remains proposal architecture.</p>
        </div>
        {metadata.data && <StatusBadge label={metadata.data.mode_label} />}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <LineageCard title="Implemented / evaluated" items={["LightGBM log-ratio global expert", "Validated multimodal ablation with weather, production, satellite, market/static, and dynamic graph features", "7-day all-modalities/dynamic-graph winner and 14-day price/calendar winner", "Seven chronological rolling origins with offline OOF replay"]} />
        <LineageCard title="Evidence-aware product layer" items={["Forecast-time / realized-time separation", "Configurable warning heuristics", "Availability and freshness states", "Fail-closed Copilot validator"]} />
        <LineageCard title="Proposed / roadmap" items={["TFT / TCN sequence encoders", "CNN / ViT satellite encoders", "Dynamic GNN propagation heads", "SHAP / TimeSHAP / GNN explanations"]} muted />
      </div>

      <Panel title="PasarPulse-MM proposed methodology" eyebrow="A100 concept paper alignment">
        <div className="grid gap-3 p-4 lg:grid-cols-2">
          <MethodItem title="Pilot scope" text="North Sumatra, initially covering bird's-eye chili, red/curly chili, and shallots at district/city and producer, wholesale, and retail levels." />
          <MethodItem title="Asynchronous multimodal fusion" text="Daily prices and aggregated ERA5-Land weather align with bounded, cloud-aware Sentinel-2 features, annual BPS context, calendar signals, and static regional features." />
          <MethodItem title="Missing-modality handling" text="Observation age, cloud quality, masks, learned missing tokens, and modality dropout prevent delayed or absent data from being interpreted as zero." />
          <MethodItem title="Dynamic market graph" text="District–commodity–market nodes connect through adjacency, road travel, market-level links, and rolling lead–lag relationships." />
          <MethodItem title="Multi-task calibrated outputs" text="The proposal jointly predicts quantile prices, candidate shock and reference-price exceedance, propagation likelihood, and calibrated uncertainty." />
          <MethodItem title="Evaluation ladder" text="B0 seasonal-naive, B1 ARIMA, B2 price-only LSTM/GRU, B3 price-only TFT, B4 price plus weather, B5 all modalities without graph, then the proposed graph system." />
        </div>
        <div className="mx-4 mb-4 rounded-xl border border-amberpulse/25 bg-amberpulse/5 p-3 text-xs leading-relaxed text-amber-100">
          The replay now consumes the validated tree-based multimodal ablation winners. The proposal’s TFT/TCN, CNN/ViT, learned missing-token fusion, multi-task shock/propagation heads, calibrated uncertainty, and GNN explanation components remain roadmap items; feature-contract inclusion is not attribution.
        </div>
      </Panel>

      <Panel title="Benchmark table" eyebrow="Repository result artifacts" action={<div className="text-[10px] text-slate-500">Lower MAE is better</div>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[850px] text-left text-xs">
            <thead className="border-b border-line text-[10px] uppercase tracking-[.12em] text-slate-500"><tr><th className="px-4 py-3">Model</th><th className="px-4 py-3">Horizon</th><th className="px-4 py-3">MAE</th><th className="px-4 py-3">Group</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Source note</th></tr></thead>
            <tbody>{benchmarks.data?.rows.map((row, index) => <tr key={`${row.model}-${row.horizon_days}-${index}`} className="border-b border-line/50"><td className="px-4 py-3 font-medium text-white">{row.model}</td><td className="px-4 py-3">{row.horizon_days ? `${row.horizon_days}d` : "—"}</td><td className="px-4 py-3 font-semibold text-cyanpulse">{idr(row.mae_idr_per_kg)}/kg</td><td className="px-4 py-3 text-slate-400">{row.group.replaceAll("_", " ")}</td><td className="px-4 py-3">{row.headline_eligible ? <span className="text-cyanpulse">Headline eligible</span> : <span className="text-amberpulse">Excluded from headline</span>}</td><td className="max-w-[340px] px-4 py-3 text-slate-500">{row.note}</td></tr>)}</tbody>
          </table>
          {benchmarks.isLoading && <div className="p-8 text-sm text-slate-500">Loading benchmark artifacts…</div>}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Validation discipline" eyebrow="Leakage boundary"><div className="space-y-3 p-4 text-xs leading-relaxed text-slate-400"><Point text="Training labels are constrained by date + horizon ≤ forecast origin." /><Point text="Alerts and rankings use current_price and predicted_price only." /><Point text="Later target_price is shown only in the historical evaluation reveal." /><Point text="No runtime training, upstream API calls, or GPU requirement." /></div></Panel>
        <Panel title="Unavailable scientific outputs" eyebrow="Honest abstention"><div className="space-y-3 p-4 text-xs leading-relaxed text-slate-400"><div className="rounded-xl border border-amberpulse/25 bg-amberpulse/5 p-3 text-amber-100"><LockKeyhole size={15} className="mr-2 inline" />This forecast artifact does not contain shock probability, propagation probability, attribution, or uncertainty intervals.</div><div>Product warning labels are not confidence percentages. Graph semantics remain disabled unless a valid graph artifact is supplied.</div></div></Panel>
      </div>
    </div>
  );
}

function LineageCard({ title, items, muted = false }: { title: string; items: string[]; muted?: boolean }) {
  return <Panel title={title} className={muted ? "opacity-75" : ""}><div className="space-y-3 p-4">{items.map((item) => <div key={item} className="flex gap-2 text-xs text-slate-300">{muted ? <CircleDashed size={14} className="mt-0.5 shrink-0 text-slate-500" /> : <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-cyanpulse" />}{item}</div>)}</div></Panel>;
}

function MethodItem({ title, text }: { title: string; text: string }) {
  return <div className="rounded-xl border border-line/70 bg-ink/30 p-3"><div className="mb-1 text-[10px] font-bold uppercase tracking-[.12em] text-cyanpulse">{title}</div><div className="text-xs leading-relaxed text-slate-300">{text}</div></div>;
}

function Point({ text }: { text: string }) {
  return <div className="flex gap-2"><FlaskConical size={14} className="mt-0.5 shrink-0 text-cyanpulse" />{text}</div>;
}
