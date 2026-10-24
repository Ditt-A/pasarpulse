export function idr(value: number | null | undefined) { return value == null || Number.isNaN(value) ? "—" : `Rp${Math.round(value).toLocaleString("id-ID")}`; }
export function pct(value: number | null | undefined) { return value == null || Number.isNaN(value) ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`; }
export function shortDate(value: string | null | undefined) { if (!value) return "—"; return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value)); }
