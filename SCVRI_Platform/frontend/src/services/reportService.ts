export interface Report {
  id: string;
  title: string;
  description: string;
  category: string;
  lastRun: string;
  lastFormat?: string;
}

export const reportService = {
  formats: ["PDF", "CSV", "XLSX"] as const,

  list: async (): Promise<Report[]> => {
    const res = await fetch("/api/reports", { next: { revalidate: 60 } });
    if (!res.ok) throw new Error(`Failed to fetch reports: ${res.status}`);
    return res.json();
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
