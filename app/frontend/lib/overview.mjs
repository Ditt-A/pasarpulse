export const WARNING_COLORS = {
  HIGH: "#b34b3e",
  ELEVATED: "#bc783e",
  WATCH: "#af8d38",
  STABLE: "#7c9b71",
  INSUFFICIENT: "#d2dcd0",
};

export function resolveDashboardParams(search, metadata, current = {}) {
  const p = new URLSearchParams(search);
  const allowed = (key, values, fallback) =>
    values.includes(p.get(key))
      ? p.get(key)
      : values.includes(fallback)
        ? fallback
        : (values[0] ?? "");
  const province = p.has("province")
    ? p.get("province")
    : current.selectedProvince || "";
  return {
    commodity: allowed(
      "commodity",
      metadata.commodities.map((x) => x.code),
      current.commodity || "CRM",
    ),
    marketLevel: allowed(
      "market",
      metadata.market_levels,
      current.marketLevel || "retail",
    ),
    horizon: Number(
      allowed(
        "horizon",
        metadata.horizons.map(String),
        String(current.horizon || 7),
      ),
    ),
    origin: allowed(
      "origin",
      metadata.forecast_origins,
      current.origin || metadata.latest_origin,
    ),
    selectedProvince: /^\d{2}$/.test(province || "") ? province : "",
    view: allowed("view", ["list", "map"], current.view || "list"),
    risk: allowed(
      "warning",
      [
        "ALL",
        "ATTENTION",
        "HIGH",
        "ELEVATED",
        "WATCH",
        "STABLE",
        "INSUFFICIENT",
      ],
      current.risk || "ALL",
    ),
    search: (p.has("q") ? p.get("q") : current.search || "").slice(0, 80),
    layer: allowed(
      "layer",
      ["risk", "change", "evidence"],
      current.layer || "risk",
    ),
  };
}
export function summarizeForecasts(rows) {
  const counts = { HIGH: 0, ELEVATED: 0, WATCH: 0, STABLE: 0, INSUFFICIENT: 0 };
  for (const row of rows)
    if (Object.hasOwn(counts, row.warning_level)) counts[row.warning_level]++;
  return {
    counts,
    provinces: new Set(rows.map((x) => x.province_code)).size,
    attention: counts.HIGH + counts.ELEVATED + counts.WATCH,
    largest: [...rows].sort(
      (a, b) => b.projected_change_pct - a.projected_change_pct,
    )[0],
  };
}
export function rankForecasts(
  rows,
  {
    search = "",
    warning = "ALL",
    sort = "projected_change_pct",
    direction = "desc",
  } = {},
) {
  const q = search.trim().toLocaleLowerCase();
  return rows
    .filter(
      (x) =>
        (!q || x.province_name.toLocaleLowerCase().includes(q)) &&
        (warning === "ALL" ||
          (warning === "ATTENTION"
            ? ["HIGH", "ELEVATED", "WATCH"].includes(x.warning_level)
            : x.warning_level === warning)),
    )
    .sort((a, b) => {
      const order =
        sort === "province_name"
          ? a.province_name.localeCompare(b.province_name)
          : Number(a[sort]) - Number(b[sort]);
      return (
        (direction === "asc" ? order : -order) ||
        a.province_name.localeCompare(b.province_name)
      );
    });
}
export function forecastsToCsv(rows) {
  const columns = [
    "province_name",
    "commodity_name",
    "market_level",
    "forecast_origin",
    "target_date",
    "horizon_days",
    "current_price",
    "predicted_price",
    "projected_change_pct",
    "warning_level",
    "model",
  ];
  const quote = (value) =>
    '"' + String(value ?? "").replaceAll('"', '""') + '"';
  return [
    columns.join(","),
    ...rows.map((row) => columns.map((key) => quote(row[key])).join(",")),
  ].join("\r\n");
}
