import { create } from "zustand";

interface DashboardState { origin: string; commodity: string; marketLevel: string; horizon: number; selectedProvince: string; selectedForecastId: string; layer: string; reveal: boolean; copilotOpen: boolean; set: (value: Partial<DashboardState>) => void; setCopilotOpen: (value: boolean) => void; }
export const useDashboardStore = create<DashboardState>((set) => ({ origin: "", commodity: "CRM", marketLevel: "retail", horizon: 7, selectedProvince: "", selectedForecastId: "", layer: "risk", reveal: false, copilotOpen: false, set: (value) => set(value), setCopilotOpen: (value) => set({ copilotOpen: value }) }));
