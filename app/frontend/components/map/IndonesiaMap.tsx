"use client";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibregl, {
  type Map as MapLibreMap,
  type ExpressionSpecification,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { GeoFeature, GeoJson } from "@/lib/types";
import { WARNING_COLORS } from "@/lib/overview.mjs";

const BOUNDS: [[number, number], [number, number]] = [
  [94.2, -11.8],
  [141.5, 6.8],
];
const riskColors: ExpressionSpecification = [
  "match",
  ["get", "warning_level"],
  "HIGH",
  WARNING_COLORS.HIGH,
  "ELEVATED",
  WARNING_COLORS.ELEVATED,
  "WATCH",
  WARNING_COLORS.WATCH,
  "STABLE",
  WARNING_COLORS.STABLE,
  WARNING_COLORS.INSUFFICIENT,
];
const changeColors: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["coalesce", ["get", "projected_change_pct"], 0],
  -5,
  "#7c9b71",
  0,
  "#e1e9d5",
  5,
  "#d6bc74",
  10,
  "#cd966b",
  20,
  "#b34b3e",
];
const evidenceColors: ExpressionSpecification = [
  "match",
  ["get", "evidence_status"],
  "AVAILABLE_CONTEXT",
  "#7c9b71",
  "#d2dcd0",
];
function paint(layer: string): ExpressionSpecification {
  return [
    "case",
    ["boolean", ["get", "has_forecast"], false],
    layer === "change"
      ? changeColors
      : layer === "evidence"
        ? evidenceColors
        : riskColors,
    "#d2dcd0",
  ];
}
function featureBounds(feature?: GeoFeature) {
  if (!feature?.geometry) return null;
  const bounds = new maplibregl.LngLatBounds();
  const walk = (value: unknown) => {
    if (!Array.isArray(value)) return;
    if (
      value.length >= 2 &&
      typeof value[0] === "number" &&
      typeof value[1] === "number"
    )
      bounds.extend([value[0], value[1]]);
    else value.forEach(walk);
  };
  walk((feature.geometry as { coordinates?: unknown }).coordinates);
  return bounds.isEmpty() ? null : bounds;
}
const graticule = {
  type: "FeatureCollection" as const,
  features: [
    ...Array.from({ length: 6 }, (_, i) => ({
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [90 + i * 10, -16],
          [90 + i * 10, 12],
        ],
      },
    })),
    ...[-10, -5, 0, 5, 10].map((lat) => ({
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: [
          [90, lat],
          [145, lat],
        ],
      },
    })),
  ],
};

export function IndonesiaMap({
  geojson,
  layer,
  selectedProvince = "",
  resetKey = 0,
  visibleProvinces,
  onSelect,
}: {
  geojson?: GeoJson;
  layer: string;
  selectedProvince?: string;
  resetKey?: number;
  visibleProvinces?: string[];
  onSelect: (code: string, forecastId?: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const latest = useRef({ geojson, layer, selectedProvince, onSelect });
  latest.current = { geojson, layer, selectedProvince, onSelect };
  const [hovered, setHovered] = useState<{
    name: string;
    change: string;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [sourceReady, setSourceReady] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    let map: MapLibreMap;
    try {
      map = new maplibregl.Map({
        container: ref.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#edf2ec" },
            },
          ],
        },
        bounds: BOUNDS,
        fitBoundsOptions: { padding: 25 },
        maxBounds: [
          [80, -45],
          [155, 45],
        ],
        minZoom: 1.2,
        maxZoom: 10,
        attributionControl: false,
        renderWorldCopies: false,
      });
    } catch {
      setFailed(true);
      return;
    }
    mapRef.current = map;
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "bottom-right",
    );
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: "Batas provinsi · BIG",
      }),
      "bottom-right",
    );
    map.on("sourcedata", (event) => {
      if (event.sourceId === "provinces" && map.getSource("provinces"))
        setSourceReady(map.isSourceLoaded("provinces"));
    });
    map.on("load", () => {
      map.addSource("grid", { type: "geojson", data: graticule });
      map.addLayer({
        id: "grid",
        type: "line",
        source: "grid",
        paint: {
          "line-color": "#dce5d8",
          "line-width": 0.65,
          "line-dasharray": [2, 5],
        },
      });
      map.addSource("provinces", {
        type: "geojson",
        data: (latest.current.geojson || {
          type: "FeatureCollection",
          features: [],
        }) as GeoJSON.FeatureCollection,
        promoteId: "province_code",
      });
      map.addLayer({
        id: "province-context",
        type: "fill",
        source: "provinces",
        paint: { "fill-color": "#e5ebe6", "fill-opacity": 1 },
      });
      map.addLayer({
        id: "province-fill",
        type: "fill",
        source: "provinces",
        paint: {
          "fill-color": paint(latest.current.layer),
          "fill-opacity": [
            "case",
            ["boolean", ["feature-state", "hover"], false],
            0.95,
            0.82,
          ],
        },
      });
      map.addLayer({
        id: "province-line",
        type: "line",
        source: "provinces",
        paint: { "line-color": "#f9fbf6", "line-width": 0.9 },
      });
      map.addLayer({
        id: "province-selected",
        type: "line",
        source: "provinces",
        filter: [
          "==",
          ["get", "province_code"],
          latest.current.selectedProvince || "__none__",
        ],
        paint: { "line-color": "#2e4c36", "line-width": 2 },
      });
      let previousHover: string | number | undefined;
      map.on("mousemove", (event) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = map.queryRenderedFeatures(event.point, {
          layers: ["province-fill", "province-line"],
        })[0];
        if (!feature) {
          map.getCanvas().style.cursor = "";
          setHovered(null);
          return;
        }
        if (previousHover != null)
          map.setFeatureState(
            { source: "provinces", id: previousHover },
            { hover: false },
          );
        previousHover = feature?.id;
        if (previousHover != null)
          map.setFeatureState(
            { source: "provinces", id: previousHover },
            { hover: true },
          );
        if (feature) {
          const change = feature.properties.projected_change_pct;
          setHovered({
            name: String(feature.properties.province_name),
            change:
              feature.properties.has_forecast && change != null
                ? `${Number(change) >= 0 ? "+" : ""}${Number(change).toFixed(1)}% proyeksi`
                : "Belum ada proyeksi pada snapshot ini",
          });
        }
      });
      map.on("mouseout", () => {
        map.getCanvas().style.cursor = "";
        setHovered(null);
        if (previousHover != null)
          map.setFeatureState(
            { source: "provinces", id: previousHover },
            { hover: false },
          );
      });
      // Include boundary strokes so narrow islands and province edges remain selectable.
      map.on("click", (event) => {
        const p = map.queryRenderedFeatures(event.point, {
          layers: ["province-fill", "province-line"],
        })[0]?.properties;
        if (p)
          latest.current.onSelect(
            String(p.province_code),
            p.forecast_id ? String(p.forecast_id) : undefined,
          );
      });
      const regions: [string, [number, number]][] = [
        ["SUMATRA", [101.5, 2.6]],
        ["JAVA", [110, -9]],
        ["KALIMANTAN", [114, 1.5]],
        ["SULAWESI", [121, 3]],
        ["MALUKU", [128, 1]],
        ["PAPUA", [137.5, -2]],
      ];
      for (const [name, coordinate] of regions) {
        const element = document.createElement("span");
        element.className = "map-region";
        element.textContent = name;
        new maplibregl.Marker({ element, anchor: "center" })
          .setLngLat(coordinate)
          .addTo(map);
      }
      setLoaded(true);
    });
    const observer = new ResizeObserver(() => {
      map.resize();
      const current = latest.current;
      const bounds = featureBounds(
        current.geojson?.features.find(
          (x) =>
            String(x.properties.province_code) === current.selectedProvince,
        ),
      );
      map.fitBounds(bounds || BOUNDS, {
        padding: bounds ? 65 : 25,
        maxZoom: bounds ? 6.2 : 4.5,
        duration: 0,
      });
    });
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    const source = map.getSource("provinces") as maplibregl.GeoJSONSource;
    if (geojson) {
      setSourceReady(false);
      source.setData(geojson as GeoJSON.FeatureCollection);
    }
  }, [geojson, loaded]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    map.setPaintProperty("province-fill", "fill-color", paint(layer));
    const filter: ExpressionSpecification | null = visibleProvinces
      ? ["in", ["get", "province_code"], ["literal", visibleProvinces]]
      : null;
    map.setFilter("province-fill", filter);
    map.setFilter("province-line", filter);
    setHovered(null);
  }, [layer, loaded, visibleProvinces]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    map.setFilter("province-selected", [
      "==",
      ["get", "province_code"],
      selectedProvince || "__none__",
    ]);
    const feature = geojson?.features.find(
      (x) => String(x.properties.province_code) === selectedProvince,
    );
    const bounds = selectedProvince ? featureBounds(feature) : null;
    map.fitBounds(bounds || BOUNDS, {
      padding: bounds ? 65 : 25,
      maxZoom: bounds ? 6.2 : 4.5,
      duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? 0
        : 450,
    });
  }, [selectedProvince, resetKey, loaded, geojson]);
  return (
    <div
      className="relative h-full w-full"
      aria-label="Peta interaktif proyeksi provinsi"
      role="region"
      data-map-ready={sourceReady}
    >
      <div ref={ref} className="h-full w-full" />
      {!sourceReady && !failed && (
        <div
          role="status"
          className="absolute left-3 top-3 rounded border border-line bg-white px-3 py-2 text-xs text-[#68736c]"
        >
          Memuat geometri wilayah…
        </div>
      )}
      {failed && (
        <div className="absolute inset-0 empty-state">
          <p>Peta belum dapat ditampilkan pada browser ini.</p>
          <p>Gunakan tampilan daftar untuk memilih provinsi.</p>
        </div>
      )}
      {hovered && (
        <output className="map-hover">
          <strong>{hovered.name}</strong>
          <span className="text-[#72806c]">{hovered.change}</span>
        </output>
      )}
    </div>
  );
}
