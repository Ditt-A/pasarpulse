"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, FlaskConical, Info, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { idr } from "@/components/common/format";
import { RequestState } from "@/components/common/RequestState";

const groupNames: Record<string, string> = {
  multimodal_ablation: "Validated multimodal study",
  saved_a100_search: "Saved A100 architecture search",
  compact_visible_rerun: "Compact executable rerun",
  prior_fold_meta: "Prior-fold meta models",
  a100_experiment: "A100 experiments",
  proposal_named_tree_variant: "Proposal-named tree variants",
  diagnostic_same_fold_weighting: "Diagnostic · same-fold weighted",
};
export default function ModelPage() {
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  const benchmarks = useQuery({
    queryKey: ["benchmarks"],
    queryFn: api.benchmarks,
  });
  const [group, setGroup] = useState("multimodal_ablation");
  const [horizon, setHorizon] = useState("ALL");
  const groups = useMemo(
    () =>
      Array.from(
        new Set((benchmarks.data?.rows || []).map((row) => row.group)),
      ),
    [benchmarks.data],
  );
  const rows = useMemo(
    () =>
      (benchmarks.data?.rows || [])
        .filter(
          (row) =>
            row.group === group &&
            (horizon === "ALL" || row.horizon_days === Number(horizon)),
        )
        .sort(
          (a, b) =>
            (a.horizon_days || 0) - (b.horizon_days || 0) ||
            a.mae_idr_per_kg - b.mae_idr_per_kg,
        ),
    [benchmarks.data, group, horizon],
  );
  const winners = [7, 14].map((days) =>
    benchmarks.data?.rows.find(
      (row) =>
        row.group === "multimodal_ablation" &&
        row.horizon_days === days &&
        metadata.data?.models.includes(row.model),
    ),
  );
  if (benchmarks.isError || metadata.isError)
    return (
      <RequestState
        error
        retry={() => {
          void benchmarks.refetch();
          void metadata.refetch();
        }}
      />
    );
  if (!benchmarks.data || !metadata.data) return <RequestState />;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">Transparent by design</div>
          <h1>Model performance</h1>
          <p>
            Validated results, a clear evaluation boundary, and traceable
            sources.
          </p>
        </div>
        <ShieldCheck
          size={25}
          strokeWidth={1.4}
          className="hidden text-[#718969] sm:block"
        />
      </div>
      <section
        className="summary-grid model-summary"
        aria-label="Replay model validation"
      >
        {winners.map((row, i) => (
          <article key={i} className="summary-card">
            <div className="summary-top">
              {i === 0 ? "7-day replay model MAE" : "14-day replay model MAE"}
              <span className="summary-icon">
                <FlaskConical size={16} />
              </span>
            </div>
            <strong className="!text-[26px]">
              {row ? idr(row.mae_idr_per_kg) : "—"}
              <small>/ kg</small>
            </strong>
            <p>Validated multimodal study · lower is better</p>
          </article>
        ))}
        <article className="summary-card">
          <div className="summary-top">
            Chronological evaluation
            <span className="summary-icon">
              <ShieldCheck size={16} />
            </span>
          </div>
          <strong>
            {metadata.data.forecast_origins.length}
            <small>origins</small>
          </strong>
          <p>Forecasts evaluated in time order</p>
        </article>
      </section>
      <div className="notice mb-5">
        <Info size={15} />
        <span>
          The active dashboard serves saved forecasts from the validated 7-day
          and 14-day models. Opening a page does not train or load these models.
        </span>
      </div>
      <section className="surface">
        <div className="surface-heading">
          <div>
            <h2>Benchmark results</h2>
            <p>
              Result families are kept separate so their scores can be assessed
              in context.
            </p>
          </div>
        </div>
        <div className="table-toolbar">
          <label className="flex flex-wrap items-center gap-3 text-xs text-[#71816a]">
            Result family
            <select
              aria-label="Benchmark result family"
              value={group}
              onChange={(e) => setGroup(e.target.value)}
              className="max-w-full rounded-md border border-line bg-white p-2.5 text-xs text-[#304c36]"
            >
              {groups.map((item) => (
                <option key={item} value={item}>
                  {groupNames[item] || item.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <div className="segmented" aria-label="Benchmark horizon">
            {["ALL", "7", "14"].map((value) => (
              <button
                key={value}
                aria-pressed={horizon === value}
                onClick={() => setHorizon(value)}
              >
                {value === "ALL" ? "Both horizons" : `${value} days`}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <caption className="sr-only">
              Saved benchmark results for the selected evaluation family. Lower
              mean absolute error is better.
            </caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Horizon</th>
                <th scope="col">MAE / kg</th>
                <th scope="col">Use in headline</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.model}-${row.horizon_days}-${i}`}>
                  <td className="max-w-[360px] !whitespace-normal break-words text-[11px] font-medium">
                    {row.model}
                  </td>
                  <td>{row.horizon_days ? `${row.horizon_days} days` : "—"}</td>
                  <td className="font-semibold text-cyanpulse">
                    {idr(row.mae_idr_per_kg)}
                  </td>
                  <td>
                    <span
                      className={`status-badge ${row.headline_eligible ? "stable" : "watch"}`}
                    >
                      {row.headline_eligible ? "Eligible" : "Diagnostic only"}
                    </span>
                  </td>
                  <td className="max-w-[300px] !whitespace-normal text-[10px] leading-relaxed text-[#71816a]">
                    <code className="break-all">{row.source_file}</code>
                    <p className="mt-1">{row.note}</p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <div className="empty-state">
            No results in this family for the selected horizon.
          </div>
        )}
        <div className="panel-bottom">
          <span>{rows.length} saved results</span>
          <span>Metric: mean absolute error in IDR / kg</span>
        </div>
      </section>
      <section className="mt-5 grid gap-5 md:grid-cols-2">
        <article className="surface p-5">
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck size={17} className="text-cyanpulse" />
            <h2 className="text-sm font-semibold">
              How the replay is evaluated
            </h2>
          </div>
          <ul className="space-y-3 text-xs leading-relaxed text-[#71816a]">
            {[
              "Training labels must be known by the forecast origin: date + horizon ≤ origin.",
              "Warnings and rankings use current and predicted prices, never later realized prices.",
              "Historical outcomes are only revealed separately for retrospective evaluation.",
              "Saved A100 search scores and compact executable rerun scores remain distinct.",
            ].map((text) => (
              <li key={text} className="flex gap-2">
                <Check size={13} className="mt-1 shrink-0 text-cyanpulse" />
                {text}
              </li>
            ))}
          </ul>
        </article>
        <article className="surface p-5">
          <div className="mb-4 flex items-center gap-2">
            <BookOpen size={17} className="text-cyanpulse" />
            <h2 className="text-sm font-semibold">Understanding the warning</h2>
          </div>
          <p className="text-xs leading-relaxed text-[#71816a]">
            The model estimates a price endpoint. A configurable product rule
            then groups positive price movements into monitoring levels.
          </p>
          <div className="mt-5 grid grid-cols-2 gap-3">
            {[
              ["Stable", `< ${metadata.data.warning_thresholds.watch}%`],
              [
                "Watch",
                `${metadata.data.warning_thresholds.watch}% to <${metadata.data.warning_thresholds.elevated}%`,
              ],
              [
                "Elevated",
                `${metadata.data.warning_thresholds.elevated}% to <${metadata.data.warning_thresholds.high}%`,
              ],
              ["High", `≥ ${metadata.data.warning_thresholds.high}%`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md bg-sage/60 p-3 text-xs">
                <span className="text-[#71816a]">{label}</span>
                <strong className="ml-3 font-medium">{value}</strong>
              </div>
            ))}
          </div>
          <p className="mt-4 text-[10px] leading-relaxed text-[#71816a]">
            These are product thresholds, not probabilities or official
            regulatory limits.
          </p>
        </article>
      </section>
      <details className="surface mt-5 p-5">
        <summary className="cursor-pointer text-xs font-semibold text-[#405a38]">
          Research scope and limitations
        </summary>
        <div className="mt-5 grid gap-5 text-xs leading-relaxed text-[#71816a] md:grid-cols-2">
          <div>
            <h3 className="mb-2 font-semibold text-[#405a38]">
              Implemented and evaluated
            </h3>
            <p>
              Tree-based LightGBM experts, transformed price targets,
              contextual/relational features, chronological evaluation, and
              read-only historical replay. Context availability does not itself
              imply model attribution or causality.
            </p>
            <h3 className="mb-2 mt-4 font-semibold text-[#405a38]">
              Diagnostic blend
            </h3>
            <p>
              The same-fold inverse-MAE blend uses evaluation-fold errors for
              its weights. It is excluded from headline comparisons and is shown
              only in its diagnostic result family.
            </p>
          </div>
          <div>
            <h3 className="mb-2 font-semibold text-[#405a38]">
              Research roadmap
            </h3>
            <p>
              TFT/TCN encoders, CNN/ViT imagery encoders, learned fusion,
              dynamic GNN propagation, calibrated intervals, and shock
              probabilities remain proposal components. They are not claimed as
              deployed features.
            </p>
            <p className="mt-4">
              Satellite vegetation and annual production are regional or
              structural context, not direct observations of daily commodity
              supply. Graph-derived features do not represent verified
              shipments.
            </p>
          </div>
        </div>
      </details>
    </>
  );
}
