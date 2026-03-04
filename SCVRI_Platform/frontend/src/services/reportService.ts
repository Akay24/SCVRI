export const reportService = {
  formats: ["PDF", "CSV", "XLSX"] as const,
  schedule: async (reportId: string) => ({ reportId, status: "scheduled" as const })
};
