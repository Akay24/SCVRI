"use client";

import mapboxgl from "mapbox-gl";
import { useEffect, useRef, useState } from "react";
import { Card } from "@/design-system/components/card";
import { Drawer } from "@/design-system/components/overlays";
import { PageTitle } from "@/design-system/components/typography";

const points = [
  { id: "SUP-001", name: "Orion Metals", lng: 77.209, lat: 28.6139, risk: "weather" },
  { id: "SUP-002", name: "Pacific Circuits", lng: 121.4737, lat: 31.2304, risk: "transport" }
];

export function SupplyChainMapPage() {
  const mapRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<(typeof points)[0] | null>(null);

  useEffect(() => {
    if (!mapRef.current || !process.env.NEXT_PUBLIC_MAPBOX_TOKEN) return;
    mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
    const map = new mapboxgl.Map({ container: mapRef.current, style: "mapbox://styles/mapbox/light-v11", center: [20, 20], zoom: 1.2 });
    points.forEach((p) => {
      const marker = new mapboxgl.Marker().setLngLat([p.lng, p.lat]).addTo(map);
      marker.getElement().addEventListener("click", () => setSelected(p));
    });
    return () => map.remove();
  }, []);

  return (
    <div className="space-y-4">
      <PageTitle>Supply Chain Map</PageTitle>
      <Card className="h-[560px] p-0"><div ref={mapRef} className="h-full w-full" /></Card>
      {!process.env.NEXT_PUBLIC_MAPBOX_TOKEN && <p className="text-sm text-amber-700">Set NEXT_PUBLIC_MAPBOX_TOKEN to enable map rendering.</p>}
      {selected && <div className="fixed right-0 top-0 h-full"><Drawer title={selected.name}><p>Supplier: {selected.id}</p><p>Risk overlay: {selected.risk}</p></Drawer></div>}
    </div>
  );
}
