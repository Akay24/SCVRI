export interface Report {
  id: string;
  title: string;
  description: string;
  category: string;
  lastRun: string;
  lastFormat?: string;
}

import { reports as mockReports } from "./mockData";

export const reportService = {
  formats: ["PDF", "CSV", "XLSX"] as const,

  list: async (): Promise<Report[]> => {
    try {
      const res = await fetch("/api/reports", { next: { revalidate: 60 } });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) return data;
      }
    } catch {
      // Fallback
    }
    return mockReports as unknown as Report[];
  },

  schedule: async (reportId: string, format = "PDF"): Promise<{ reportId: string; status: string; format: string }> => {
    const res = await fetch(`/api/reports/${reportId}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format }),
    });
    if (!res.ok) throw new Error(`Failed to schedule report ${reportId}: ${res.status}`);
    return res.json();
  },
};
