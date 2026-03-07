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

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { next: { revalidate: 60 } });
  if (!res.ok) throw new Error(`${url} failed: ${res.status}`);
  return res.json();
}

export const riskService = {
  trend:     (): Promise<MetricPoint[]>  => fetchJson("/api/risk/trend"),
  byRegion:  (): Promise<MetricPoint[]>  => fetchJson("/api/risk/by-region"),
  byDriver:  (): Promise<MetricPoint[]>  => fetchJson("/api/risk/by-driver"),
  events:    (): Promise<RiskEvent[]>    => fetchJson("/api/risk/events"),
  delays:    (): Promise<MetricPoint[]>  => fetchJson("/api/risk/shipment-delays"),
  onTimeByWeek: (): Promise<WeeklyOnTime[]> => fetchJson("/api/risk/ontime-by-week"),
};
