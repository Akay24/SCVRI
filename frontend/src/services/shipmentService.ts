export interface Shipment {
  id: string;
  supplier: string;
  origin: string;
  destination: string;
  mode: "SEA" | "AIR" | "RAIL" | "ROAD";
  status: "on-track" | "delayed" | "at-risk";
  eta: string;
  daysDelayed: number;
  value: number;
  containers: number;
}

import { shipments as mockShipments } from "./mockData";

export type ShipmentDraft = Omit<Shipment, "id">;

export const shipmentService = {
  list: async (filters: { status?: string; supplier?: string } = {}): Promise<Shipment[]> => {
    try {
      const params = new URLSearchParams();
      if (filters.status)   params.set("status",   filters.status);
      if (filters.supplier) params.set("supplier", filters.supplier);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await fetch(`/api/shipments${qs}`, { next: { revalidate: 30 } });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) return data;
      }
    } catch {
      // Fallback
    }

    let result = [...mockShipments];
    if (filters.status)   result = result.filter((s) => s.status === filters.status);
    if (filters.supplier) result = result.filter((s) => s.supplier === filters.supplier);
    return result as unknown as Shipment[];
  },

  create: async (draft: ShipmentDraft): Promise<Shipment> => {
    const res = await fetch("/api/shipments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    if (!res.ok) throw new Error(`Failed to create shipment: ${res.status}`);
    return res.json();
  },

  update: async (id: string, patch: Partial<ShipmentDraft>): Promise<Shipment> => {
    const res = await fetch(`/api/shipments/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`Failed to update shipment ${id}: ${res.status}`);
    return res.json();
  },

  remove: async (id: string): Promise<void> => {
    const res = await fetch(`/api/shipments/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Failed to delete shipment ${id}: ${res.status}`);
  },

  // Chart data delegates
  delays:      () => import("./riskService").then((m) => m.riskService.delays()),
  onTimeByWeek: () => import("./riskService").then((m) => m.riskService.onTimeByWeek()),
};
