const styles: Record<string, string> = {
  STABLE: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  WATCH: "border-amber-300/50 bg-amber-300/10 text-amber-200",
  ELEVATED: "border-orange-300/50 bg-orange-300/10 text-orange-200",
  HIGH: "border-red-300/50 bg-red-300/10 text-red-200",
  INSUFFICIENT: "border-slate-400/40 bg-slate-400/10 text-slate-300",
  "HISTORICAL REPLAY": "border-cyanpulse/40 bg-cyanpulse/10 text-cyanpulse",
  "BENCHMARK ONLY": "border-amberpulse/40 bg-amberpulse/10 text-amberpulse",
};

export function StatusBadge({ label }: { label: string }) {
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-bold tracking-[.12em] ${styles[label] ?? "border-line bg-white/5 text-slate-300"}`}>{label}</span>;
}
