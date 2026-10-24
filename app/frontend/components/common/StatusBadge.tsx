const labels: Record<string, string> = {
  STABLE: "Stable",
  WATCH: "Watch",
  ELEVATED: "Elevated",
  HIGH: "High",
  INSUFFICIENT: "No forecast",
  "HISTORICAL REPLAY": "Historical replay",
  "BENCHMARK ONLY": "Benchmark only",
  "INFERENCE SNAPSHOT": "Inference snapshot",
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
