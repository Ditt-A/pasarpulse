export const DASHBOARD_ACTION_TYPES = [
  "SET_PROVINCE",
  "SET_COMMODITY",
  "SET_MARKET_LEVEL",
  "SET_HORIZON",
  "SET_MAP_LAYER",
  "SET_REPLAY_ORIGIN",
  "FILTER_RISK",
  "COMPARE_PROVINCES",
  "OPEN_ALERT",
  "RESET_FILTERS",
] as const;

export type DashboardActionType = (typeof DASHBOARD_ACTION_TYPES)[number];
export type DashboardAction = { type: string; value?: unknown };

export function isAllowedDashboardAction(action: DashboardAction): action is DashboardAction & { type: DashboardActionType } {
  if (!(DASHBOARD_ACTION_TYPES as readonly string[]).includes(action.type)) return false;
  if (action.type === "SET_COMMODITY") return typeof action.value === "string" && ["BM", "CMK", "CRM"].includes(action.value);
  if (action.type === "SET_MARKET_LEVEL") return typeof action.value === "string" && ["producer", "wholesale", "retail"].includes(action.value);
  if (action.type === "SET_HORIZON") return action.value === 7 || action.value === 14;
  if (action.type === "SET_MAP_LAYER") return typeof action.value === "string" && ["risk", "change", "evidence"].includes(action.value);
  if (action.type === "SET_REPLAY_ORIGIN") return typeof action.value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(action.value);
  if (action.type === "SET_PROVINCE") return typeof action.value === "string" && /^\d{2}$/.test(action.value);
  if (action.type === "FILTER_RISK") return Array.isArray(action.value) && action.value.every((value) => typeof value === "string" && ["STABLE", "WATCH", "ELEVATED", "HIGH", "INSUFFICIENT"].includes(value));
  if (action.type === "COMPARE_PROVINCES") return Array.isArray(action.value) && action.value.length >= 2 && action.value.length <= 4 && action.value.every((value) => typeof value === "string" && /^\d{2}$/.test(value));
  if (action.type === "OPEN_ALERT") return typeof action.value === "string" && action.value.length > 0;
  return true;
}
