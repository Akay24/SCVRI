import { riskMetrics, riskEvents } from "./mockData";

export interface MetricPoint      { name: string; value: number; }
export interface WeeklyOnTime     { name: string; onTime: number; delayed: number; }

export interface RiskEvent {
  date: string;
  type: string;
  title: string;
  region: string;
  impactedSuppliers: number;
  severityScore: number;
}

async function fetchJson<T>(url: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return fallback;
    const data = await res.json();
    return data ?? fallback;
  } catch {
    return fallback;
  }
}

export const riskService = {
  trend:     (): Promise<MetricPoint[]>  => fetchJson("/api/risk/trend", riskMetrics.trend),
  byRegion:  (): Promise<MetricPoint[]>  => fetchJson("/api/risk/by-region", riskMetrics.byRegion),
  byDriver:  (): Promise<MetricPoint[]>  => fetchJson("/api/risk/by-driver", riskMetrics.byDriver),
  events:    (): Promise<RiskEvent[]>    => fetchJson("/api/risk/events", riskEvents as unknown as RiskEvent[]),
  delays:    (): Promise<MetricPoint[]>  => fetchJson("/api/risk/shipment-delays", riskMetrics.shipmentDelays),
  onTimeByWeek: (): Promise<WeeklyOnTime[]> => fetchJson("/api/risk/ontime-by-week", riskMetrics.onTimeByWeek),
};
