import { create } from "zustand";

interface DashboardState {
  origin: string;
  commodity: string;
  marketLevel: string;
  horizon: number;
  selectedProvince: string;
  selectedForecastId: string;
  layer: string;
  reveal: boolean;
  copilotOpen: boolean;
  set: (value: Partial<DashboardState>) => void;
  setCopilotOpen: (value: boolean) => void;
}
export const useDashboardStore = create<DashboardState>((set) => ({
  origin: "",
  commodity: "CRM",
  marketLevel: "retail",
  horizon: 7,
  selectedProvince: "",
  selectedForecastId: "",
  layer: "risk",
  reveal: false,
  copilotOpen: false,
  set: (value) =>
    set((current) => {
      const contextChanged = (
        [
          "origin",
          "commodity",
          "marketLevel",
          "horizon",
          "selectedProvince",
        ] as const
      ).some((key) => value[key] !== undefined && value[key] !== current[key]);
      return {
        ...value,
        ...(contextChanged
          ? {
              reveal: false,
              selectedForecastId: value.selectedForecastId ?? "",
            }
          : {}),
      };
    }),
  setCopilotOpen: (value) => set({ copilotOpen: value }),
}));
