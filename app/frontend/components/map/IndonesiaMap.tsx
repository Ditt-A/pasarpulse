"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { GeoFeature, GeoJson } from "@/lib/types";

const riskColors: any = ["match", ["get", "warning_level"], "HIGH", "#dc2626", "ELEVATED", "#f97316", "WATCH", "#eab308", "STABLE", "#0f766e", "#cbd5e1"];
const changeColors: any = ["interpolate", ["linear"], ["coalesce", ["get", "projected_change_pct"], 0], -5, "#2563eb", 0, "#bfdbfe", 5, "#fde68a", 10, "#fb923c", 20, "#dc2626"];
const evidenceColors: any = ["match", ["get", "evidence_status"], "AVAILABLE_CONTEXT", "#0f766e", "INSUFFICIENT", "#cbd5e1", "#94a3b8"];
const INDONESIA_BOUNDS: [[number, number], [number, number]] = [[94.2, -11.8], [141.5, 6.8]];
const PAN_BOUNDS: [[number, number], [number, number]] = [[91, -16], [145, 11]];

function featureBounds(feature?: GeoFeature) {
  if (!feature?.geometry) return null;
  const bounds = new maplibregl.LngLatBounds();
  let found = false;
  const walk = (value: unknown) => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      bounds.extend([value[0], value[1]]);
      found = true;
      return;
    }
    value.forEach(walk);
  };
  walk((feature.geometry as { coordinates?: unknown }).coordinates);
  return found ? bounds : null;
}

export function IndonesiaMap({ geojson, layer, selectedProvince, onSelect }: { geojson?: GeoJson; layer: string; selectedProvince?: string; onSelect: (provinceCode: string, forecastId?: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const selectRef = useRef(onSelect);
  const [hovered, setHovered] = useState<string | null>(null);
  selectRef.current = onSelect;

  useEffect(() => {
    if (!ref.current || !geojson || mapRef.current) return;

    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {
          "light-basemap": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors © CARTO",
          },
        },
        layers: [
          { id: "background", type: "background", paint: { "background-color": "#f8fafc" } },
          { id: "light-basemap", type: "raster", source: "light-basemap", paint: { "raster-opacity": 0.88 } },
        ],
      } as any,
      bounds: INDONESIA_BOUNDS,
      fitBoundsOptions: { padding: 44 },
      maxBounds: PAN_BOUNDS,
      minZoom: 3.25,
      maxZoom: 10,
      renderWorldCopies: true,
      attributionControl: false,
    });

    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.addSource("provinces", { type: "geojson", data: geojson as any });
      map.addLayer({
        id: "province-fill",
        type: "fill",
        source: "provinces",
        paint: {
          "fill-color": riskColors,
          "fill-opacity": ["case", ["get", "has_forecast"], 0.72, 0.18],
        },
      });
      map.addLayer({
        id: "province-line",
        type: "line",
        source: "provinces",
        paint: { "line-color": "#ffffff", "line-opacity": 0.95, "line-width": 0.8 },
      });
      map.addLayer({
        id: "province-selected",
        type: "line",
        source: "provinces",
        filter: ["==", ["get", "province_code"], selectedProvince || "__none__"],
        paint: { "line-color": "#0f172a", "line-opacity": 1, "line-width": 2.8 },
      });

      map.on("click", "province-fill", (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        selectRef.current(
          String(feature.properties?.province_code || ""),
          feature.properties?.forecast_id ? String(feature.properties.forecast_id) : undefined,
        );
      });
      map.on("mousemove", "province-fill", (event) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = event.features?.[0];
        setHovered(feature ? `${feature.properties?.province_name || "Province"} · ${feature.properties?.warning_level || "INSUFFICIENT"}` : null);
      });
      map.on("mouseleave", "province-fill", () => {
        map.getCanvas().style.cursor = "";
        setHovered(null);
      });
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [geojson]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geojson) return;
    const source = map.getSource("provinces") as maplibregl.GeoJSONSource | undefined;
    if (source) source.setData(geojson as any);
    if (map.getLayer("province-fill")) {
      map.setPaintProperty("province-fill", "fill-color", layer === "change" ? changeColors : layer === "evidence" ? evidenceColors : riskColors);
    }
  }, [geojson, layer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedProvince || !geojson) return;
    if (map.getLayer("province-selected")) map.setFilter("province-selected", ["==", ["get", "province_code"], selectedProvince]);
    const feature = geojson.features.find((item) => String(item.properties.province_code || "") === selectedProvince);
    const bounds = featureBounds(feature);
    if (bounds) map.fitBounds(bounds, { padding: 120, maxZoom: 6.4, duration: 650 });
  }, [selectedProvince, geojson]);

  const layerTitle = layer === "change" ? "Projected change" : layer === "evidence" ? "Evidence" : "Price-shock risk";

  return (
    <div className="relative h-full w-full overflow-hidden bg-slate-100">
      <div ref={ref} className="h-full w-full" />
      <div className="pointer-events-none absolute bottom-7 left-3 rounded-xl border border-slate-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur sm:left-14">
        <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">{layerTitle}</div>
        {layer === "evidence" ? (
          <div className="flex gap-3 text-[10px] font-medium text-slate-700"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-teal-700" />Available</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-slate-300" />Insufficient</span></div>
        ) : (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] font-medium text-slate-700"><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-red-600" />High</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-orange-500" />Elevated</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-yellow-500" />Watch</span><span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-teal-700" />Stable</span></div>
        )}
      </div>
      {hovered && <div className="pointer-events-none absolute bottom-7 right-3 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs font-semibold text-slate-800 shadow-sm backdrop-blur sm:right-12">{hovered}</div>}
    </div>
  );
}
