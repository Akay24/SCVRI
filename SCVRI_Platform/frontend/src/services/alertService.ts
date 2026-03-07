export type AlertSeverity = "critical" | "high" | "medium" | "low";
export type AlertStatus   = "open" | "acknowledged" | "resolved";

export interface Alert {
  id: string;
  title: string;
  severity: AlertSeverity;
  status: AlertStatus;
  assignedTo: string;
  category: string;
  supplier: string;
  createdAt: string;
  region: string;
}

export type AlertDraft = Omit<Alert, "id" | "status" | "createdAt">;

export const alertService = {
  list: async (filters: { severity?: string; status?: string; region?: string } = {}): Promise<Alert[]> => {
    const params = new URLSearchParams();
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.status)   params.set("status",   filters.status);
    if (filters.region)   params.set("region",   filters.region);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const res = await fetch(`/api/alerts${qs}`, { next: { revalidate: 30 } });
    if (!res.ok) throw new Error(`Failed to fetch alerts: ${res.status}`);
    return res.json();
  },

  acknowledge: async (id: string): Promise<Alert> => {
    const res = await fetch(`/api/alerts/${id}/acknowledge`, { method: "PATCH" });
    if (!res.ok) throw new Error(`Failed to acknowledge alert ${id}: ${res.status}`);
    return res.json();
  },

  create: async (draft: AlertDraft): Promise<Alert> => {
    const res = await fetch("/api/alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    if (!res.ok) throw new Error(`Failed to create alert: ${res.status}`);
    return res.json();
  },

  update: async (id: string, patch: Partial<Alert>): Promise<Alert> => {
    const res = await fetch(`/api/alerts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`Failed to update alert ${id}: ${res.status}`);
    return res.json();
  },

  remove: async (id: string): Promise<void> => {
    const res = await fetch(`/api/alerts/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Failed to delete alert ${id}: ${res.status}`);
  },
};
