import type { Forecast, Metadata, WarningLevel } from "./types";
export const WARNING_COLORS: Record<WarningLevel, string>;
export interface DashboardContext {
  commodity: string;
  marketLevel: string;
  horizon: number;
  origin: string;
  selectedProvince: string;
  layer: string;
  view: "list" | "map";
  risk: string;
  search: string;
}
export function resolveDashboardParams(
  search: string,
  metadata: Metadata,
  current?: Partial<DashboardContext>,
): DashboardContext;
export function summarizeForecasts(rows: Forecast[]): {
  counts: Record<WarningLevel, number>;
  provinces: number;
  attention: number;
  largest?: Forecast;
};
export interface RankingOptions {
  search?: string;
  warning?: string;
  sort?:
    | "province_name"
    | "current_price"
    | "predicted_price"
    | "projected_change_pct";
  direction?: "asc" | "desc";
}
export function rankForecasts(
  rows: Forecast[],
  options?: RankingOptions,
): Forecast[];
export function forecastsToCsv(rows: Forecast[]): string;
