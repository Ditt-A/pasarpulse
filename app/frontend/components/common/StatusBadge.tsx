const labels: Record<string, string> = {
  STABLE: "Stabil",
  WATCH: "Waspada",
  ELEVATED: "Meningkat",
  HIGH: "Tinggi",
  INSUFFICIENT: "Data terbatas",
  "HISTORICAL REPLAY": "Replay historis",
  "BENCHMARK ONLY": "Benchmark",
  "INFERENCE SNAPSHOT": "Snapshot inferensi",
};
export function StatusBadge({ label }: { label: string }) {
  const kind = ["STABLE", "WATCH", "ELEVATED", "HIGH", "INSUFFICIENT"].includes(
    label,
  )
    ? label.toLowerCase()
    : "mode";
  return (
    <span className={`status-badge ${kind}`}>
      <i aria-hidden="true" />
      {labels[label] || label}
    </span>
  );
}
