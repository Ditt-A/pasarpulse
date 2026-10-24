"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { resolveDashboardParams } from "./overview.mjs";
import { useDashboardStore } from "@/stores/dashboard";

export function useForecastContext(syncUrl = false) {
  const state = useDashboardStore();
  const set = useDashboardStore((value) => value.set);
  const metadata = useQuery({ queryKey: ["metadata"], queryFn: api.metadata });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!metadata.data) return;
    const restore = () =>
      set(
        resolveDashboardParams(
          window.location.search,
          metadata.data!,
          useDashboardStore.getState(),
        ),
      );
    restore();
    setReady(true);
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, [metadata.data, set]);
  useEffect(() => {
    if (!ready || !syncUrl || !state.origin) return;
    const params = new URLSearchParams({
      commodity: state.commodity,
      market: state.marketLevel,
      horizon: String(state.horizon),
      origin: state.origin,
    });
    if (state.selectedProvince) params.set("province", state.selectedProvince);
    if (state.layer !== "risk") params.set("layer", state.layer);
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?${params}`,
    );
  }, [
    ready,
    syncUrl,
    state.commodity,
    state.marketLevel,
    state.horizon,
    state.origin,
    state.selectedProvince,
    state.layer,
  ]);
  const params = {
    origin: state.origin || undefined,
    commodity: state.commodity,
    market_level: state.marketLevel,
    horizon: state.horizon,
  };
  return { state, metadata, ready, params };
}
