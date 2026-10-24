"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useForecastContext } from "@/lib/useForecastContext";
import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { RequestState } from "@/components/common/RequestState";
export default function AssistantPage() {
  const { state, metadata, ready, params } = useForecastContext();
  const forecasts = useQuery({
    queryKey: ["forecasts", params],
    queryFn: () => api.forecasts(params),
    enabled: ready,
  });
  const selected = state.selectedProvince
    ? forecasts.data?.find(
        (row) => row.province_code === state.selectedProvince,
      )
    : forecasts.data?.[0];
  if (metadata.isError || forecasts.isError)
    return (
      <RequestState
        error
        retry={() => {
          void metadata.refetch();
          void forecasts.refetch();
        }}
      />
    );
  if (!ready || forecasts.isPending) return <RequestState />;
  return <CopilotPanel forecast={selected} standalone />;
}
