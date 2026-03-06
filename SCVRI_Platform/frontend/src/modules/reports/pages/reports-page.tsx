"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { reportService } from "@/services/reportService";
import { Card } from "@/design-system/components/card";
import { PageTitle, CardTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";

const REPORTS = [
  {
    id: "spend-concentration",
    title: "Spend Concentration",
    description: "Top 10 suppliers by procurement spend, with risk-adjusted exposure per tier.",
    lastRun: "2 Mar 2026",
    category: "Finance",
  },
  {
    id: "supplier-performance",
    title: "Supplier Performance Scorecard",
    description: "On-time delivery, quality rejection rate, SLA compliance across all active suppliers.",
    lastRun: "1 Mar 2026",
    category: "Operations",
  },
  {
    id: "risk-trends",
    title: "Risk Trend Analysis",
    description: "30/60/90-day rolling risk score movement by region, disruption type, and supplier tier.",
    lastRun: "5 Mar 2026",
    category: "Risk",
  },
  {
    id: "lead-time-trends",
    title: "Lead Time Trends",
    description: "Average and P95 lead times by trade lane and carrier, flagging degradation.",
    lastRun: "4 Mar 2026",
    category: "Logistics",
  },
] as const;

type ReportId = (typeof REPORTS)[number]["id"];
type Format = (typeof reportService.formats)[number];

const CATEGORY_COLOR: Record<string, string> = {
  Finance:    "bg-[#964734]/10 text-[#964734]",
  Operations: "bg-accent/10 text-accent",
  Risk:       "bg-red-100 text-red-700",
  Logistics:  "bg-[#024950]/10 text-[#024950] dark:bg-brand-powder/10 dark:text-brand-powder",
};

export function ReportsPage() {
  // Track selected format per report
  const [formats, setFormats] = useState<Record<ReportId, Format>>({} as Record<ReportId, Format>);
  // Track scheduled confirmation per report
  const [scheduled, setScheduled] = useState<Record<ReportId, boolean>>({} as Record<ReportId, boolean>);

  const mutation = useMutation({
    mutationFn: ({ reportId }: { reportId: string }) => reportService.schedule(reportId),
    onSuccess: (_, { reportId }) => {
      setScheduled((prev) => ({ ...prev, [reportId as ReportId]: true }));
      // Reset confirmation after 3 s
      setTimeout(() => setScheduled((prev) => ({ ...prev, [reportId as ReportId]: false })), 3000);
    },
  });

  function selectedFormat(id: ReportId): Format {
    return formats[id] ?? "PDF";
  }

  return (
    <div className="space-y-6">
      <PageTitle>Reports & Analytics</PageTitle>

      {/* Prebuilt reports */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-3">Prebuilt Reports</h2>
        {REPORTS.map((report) => (
          <Card key={report.id}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <p className="font-semibold text-ink">{report.title}</p>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    CATEGORY_COLOR[report.category] ?? "bg-surface text-ink-2"
                  }`}>{report.category}</span>
                </div>
                <p className="mt-1 text-sm text-ink-2">{report.description}</p>
                <p className="mt-1 text-xs text-ink-3">Last generated: {report.lastRun}</p>
              </div>

              {/* Format selector + export button */}
              <div className="flex shrink-0 items-center gap-2">
                <div className="flex rounded-lg border border-stroke bg-card text-xs">
                  {reportService.formats.map((f) => (
                    <button
                      key={f}
                      onClick={() => setFormats((prev) => ({ ...prev, [report.id]: f }))}
                      className={`px-3 py-1.5 first:rounded-l-lg last:rounded-r-lg transition-colors ${
                        selectedFormat(report.id) === f
                          ? "bg-accent text-white font-medium"
                          : "text-ink-2 hover:bg-surface"
                      }`}
                    >
                      {f}
                    </button>
                  ))}
                </div>
                <Button
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate({ reportId: report.id })}
                  className={scheduled[report.id] ? "bg-green-600 text-white" : ""}
                >
                  {scheduled[report.id] ? "Scheduled ✓" : "Export"}
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </section>

      {/* Custom builder — placeholder card */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-3">Custom Report Builder</h2>
        <Card>
          <p className="text-sm text-ink-2">
            Slice any metric by <span className="font-medium">region</span>,{" "}
            <span className="font-medium">supplier tier</span>, or{" "}
            <span className="font-medium">spend category</span> — then schedule a recurring export.
          </p>
          <p className="mt-2 text-xs text-ink-3">Custom builder · coming in v1.1</p>
        </Card>
      </section>
    </div>
  );
}
