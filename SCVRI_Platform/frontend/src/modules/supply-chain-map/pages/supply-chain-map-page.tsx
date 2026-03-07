"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/design-system/components/card";
import { Drawer } from "@/design-system/components/overlays";
import { PageTitle } from "@/design-system/components/typography";
import { supplierService, type Supplier } from "@/services/supplierService";

// Free OpenFreeMap tile style — no token required
const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

// Approximate coordinates per supplier country/city
const COORDS: Record<string, [number, number]> = {
  "India":        [77.209,  28.614],
  "Taiwan":       [121.474, 25.033],
  "Sweden":       [18.068,  59.333],
  "Germany":      [13.405,  52.520],
  "South Korea":  [126.978, 37.566],
  "USA":          [-87.629, 41.878],
  "China":        [114.058, 22.543],
  "Canada":       [-123.12, 49.283],
  "Netherlands":  [4.9041,  52.367],
  "Israel":       [34.852,  31.046],
  "Egypt":        [31.225,  30.044],
  "Mexico":       [-99.133, 19.433],
};

const RISK_COLOR = (score: number) =>
  score >= 70 ? "#ef4444" : score >= 45 ? "#f97316" : "#22c55e";

export function SupplyChainMapPage() {
  const mapRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<Supplier | null>(null);
  const [mapReady, setMapReady] = useState(false);

  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers"],
    queryFn: supplierService.list,
  });

  useEffect(() => {
    if (!mapRef.current || suppliers.length === 0) return;

    const map = new maplibregl.Map({
      container: mapRef.current,
      style: MAP_STYLE,
      center: [20, 20],
      zoom: 1.2,
    });

    map.on("load", () => setMapReady(true));

    const handlers: Array<() => void> = [];

    suppliers.forEach((s) => {
      const coords = COORDS[s.country];
      if (!coords) return;

      const el = document.createElement("div");
      el.style.cssText = `
        width:14px; height:14px; border-radius:50%;
        background:${RISK_COLOR(s.riskScore)};
        border:2px solid white;
        box-shadow:0 1px 4px rgba(0,0,0,.35);
        cursor:pointer;
      `;
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat(coords)
        .addTo(map);

      const handler = () => setSelected(s);
      el.addEventListener("click", handler);
      handlers.push(() => {
        el.removeEventListener("click", handler);
        marker.remove();
      });
    });

    return () => {
      handlers.forEach((cleanup) => cleanup());
      map.remove();
    };
  }, [suppliers]);

  return (
    <div className="space-y-4">
      {/* Legend */}
      <div className="flex items-center justify-between">
        <PageTitle>Supply Chain Map</PageTitle>
        <div className="flex items-center gap-4 text-xs text-ink-3">
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full bg-red-400" />High risk (≥70)</span>
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full bg-orange-400" />Medium (45–69)</span>
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full bg-green-500" />Low (&lt;45)</span>
        </div>
      </div>

      <Card className="relative h-[560px] p-0 overflow-hidden">
        <div ref={mapRef} className="h-full w-full" />
        {!mapReady && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface">
            <div className="flex flex-col items-center gap-2 text-sm text-ink-3">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
              Loading map…
            </div>
          </div>
        )}
      </Card>

      {selected && (
        <div className="fixed right-0 top-0 h-full z-40">
          <Drawer title={selected.name}>
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-surface p-3">
                  <p className="text-xs text-ink-3">Risk score</p>
                  <p className={`mt-1 text-xl font-bold ${selected.riskScore >= 70 ? "text-red-600" : selected.riskScore >= 45 ? "text-orange-500" : "text-green-600"}`}>{selected.riskScore}</p>
                </div>
                <div className="rounded-lg bg-surface p-3">
                  <p className="text-xs text-ink-3">Tier</p>
                  <p className="mt-1 text-xl font-bold text-ink">{selected.tier}</p>
                </div>
                <div className="rounded-lg bg-surface p-3">
                  <p className="text-xs text-ink-3">Annual spend</p>
                  <p className="mt-1 font-semibold text-ink-2">${(selected.spend / 1_000_000).toFixed(1)}M</p>
                </div>
                <div className="rounded-lg bg-surface p-3">
                  <p className="text-xs text-ink-3">Active POs</p>
                  <p className="mt-1 font-semibold text-ink-2">{selected.activePOs}</p>
                </div>
              </div>
              <p className="text-xs text-ink-3">{selected.country} · {selected.region} · {selected.category}</p>
              <p className="text-xs text-ink-3">OTD: <span className="font-semibold text-ink-2">{selected.onTimeDelivery}%</span> · Quality yield: <span className="font-semibold text-ink-2">{selected.qualityYield}%</span></p>
              <p className="text-xs text-ink-3">In transit: {selected.inTransit} shipments · {selected.delayed} delayed</p>
            </div>
            <button onClick={() => setSelected(null)} className="mt-5 text-xs text-accent underline">
              Close
            </button>
          </Drawer>
        </div>
      )}
    </div>
  );
}
