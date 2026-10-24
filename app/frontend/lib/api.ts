import type {
  Alert,
  AuditedXaiSample,
  Benchmark,
  CopilotResult,
  Evidence,
  Forecast,
  ForecastXai,
  GeoJson,
  Metadata,
} from "./types";

// Keep browser requests same-origin so the dashboard works over WireGuard.
// Next.js rewrites /api/* to the internal FastAPI service.
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "");
async function responseError(response: Response): Promise<Error> {
  const fallback = `API error ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: string };
    return new Error(body.detail || fallback);
  } catch {
    return new Error(fallback);
  }
}
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}
function query(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "")
      search.set(key, String(value));
  });
  return search.toString();
}
export const api = {
  health: () =>
    get<{ reasoning_service: { status: string; detail: string } }>("/health"),
  metadata: () => get<Metadata>("/metadata"),
  forecasts: (
    params: Record<string, string | number | undefined | null> = {},
  ) => get<Forecast[]>(`/forecasts?${query(params)}`),
  forecast: (id: string, reveal = false) =>
    get<Forecast>(
      `/forecasts/${encodeURIComponent(id)}?reveal=${reveal ? "true" : "false"}`,
    ),
  alerts: (params: Record<string, string | number | undefined | null> = {}) =>
    get<Alert[]>(`/alerts?${query(params)}`),
  provinces: (
    params: Record<string, string | number | undefined | null> = {},
  ) => get<GeoJson>(`/provinces?${query(params)}`),
  evidence: (id: string) =>
    get<Evidence>(`/evidence/${encodeURIComponent(id)}`),
  auditedXaiSamples: () => get<AuditedXaiSample[]>("/xai/audited-samples"),
  forecastXai: (id: string) =>
    get<ForecastXai>(`/xai/forecasts/${encodeURIComponent(id)}`),
  benchmarks: () =>
    get<{
      rows: Benchmark[];
      headline_rows: Benchmark[];
      excluded_rows: Benchmark[];
      note: string;
    }>("/benchmarks"),
  copilot: async (message: string, context: unknown) => {
    const response = await fetch(`${API_URL}/copilot/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, context }),
    });
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<CopilotResult>;
  },
};
