"use client";

import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import GridLayout, { WidthProvider } from "react-grid-layout";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/design-system/components/card";
import { PageTitle, CardTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { LazyBarChart, LazyLineChart } from "@/components/charts/reusable-charts";
import { riskService } from "@/services/riskService";
import { shipmentService } from "@/services/shipmentService";
import { supplierService } from "@/services/supplierService";

const ResponsiveGridLayout = WidthProvider(GridLayout);

/** Six-dot grip icon — signals the title bar is draggable */
function GripIcon() {
  return (
    <svg
      className="h-4 w-4 shrink-0 text-ink-3"
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
    >
      <circle cx="5" cy="4" r="1.4" />
      <circle cx="11" cy="4" r="1.4" />
      <circle cx="5" cy="8" r="1.4" />
      <circle cx="11" cy="8" r="1.4" />
      <circle cx="5" cy="12" r="1.4" />
      <circle cx="11" cy="12" r="1.4" />
    </svg>
  );
}

/** Small KPI stat card used in the top row */
function StatCard({ label, value, sub, color = "text-ink" }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="flex flex-col justify-between rounded-xl border border-stroke bg-card p-5 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
      <p className={`mt-2 text-3xl font-bold tabular-nums ${color}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-ink-3">{sub}</p>}
    </div>
  );
}

export function DashboardPage() {
  const riskTrend = useQuery({ queryKey: ["risk-trend"], queryFn: riskService.trend });
  const shipmentDelay = useQuery({ queryKey: ["shipment-delay"], queryFn: shipmentService.delays });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: supplierService.list });

  const anyLoading = riskTrend.isPending || shipmentDelay.isPending || suppliers.isPending;
  const anyError = riskTrend.isError || shipmentDelay.isError || suppliers.isError;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <PageTitle>Executive Dashboard</PageTitle>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-stroke bg-card text-sm shadow-sm">
            {(["7d", "30d", "90d"] as const).map((r) => (
              <button
                key={r}
                className={`px-4 py-1.5 first:rounded-l-lg last:rounded-r-lg transition-colors ${
                  r === "7d" ? "bg-accent text-white font-medium" : "text-ink-2 hover:bg-surface"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <Button>Export</Button>
        </div>
      </div>

      {anyError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Some data failed to load — displaying partial results.
        </div>
      )}

      {anyLoading ? (
        <div className="space-y-4 animate-pulse">
          <div className="grid grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => <div key={i} className="h-28 rounded-xl bg-surface" />)}
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[...Array(2)].map((_, i) => <div key={i} className="h-64 rounded-xl bg-surface" />)}
          </div>
          <div className="h-56 rounded-xl bg-surface" />
        </div>
      ) : (
        <>
          {/* KPI row — static, no drag needed for 3-up stat cards */}
          <div className="grid grid-cols-3 gap-4">
            <StatCard label="Active disruptions" value="12" sub="open events" color="text-orange-600" />
            <StatCard label="Spend at risk" value="$4.2M" sub="currently exposed" color="text-red-600" />
            <StatCard label="Recent alerts" value="5" sub="critical in last 24 h" color="text-amber-600" />
          </div>

          {/* Chart row */}
          <ResponsiveGridLayout
            className="layout"
            cols={12}
            rowHeight={56}
            draggableHandle=".drag"
            margin={[16, 16]}
          >
            <div key="risk" data-grid={{ x: 0, y: 0, w: 7, h: 5, minW: 4, minH: 4 }}>
              <Card className="h-full">
                <CardTitle>
                  <span className="drag flex cursor-grab items-center gap-1.5 select-none">
                    <GripIcon />Risk heatmap
                  </span>
                </CardTitle>
                {riskTrend.data
                  ? <LazyLineChart data={riskTrend.data} />
                  : <p className="mt-4 text-xs text-ink-3">No data available</p>}
              </Card>
            </div>

            <div key="atrisk" data-grid={{ x: 7, y: 0, w: 5, h: 5, minW: 3, minH: 4 }}>
              <Card className="flex h-full flex-col overflow-hidden">
                <CardTitle>
                  <span className="drag flex cursor-grab items-center gap-1.5 select-none">
                    <GripIcon />Top at-risk suppliers
                  </span>
                </CardTitle>

                {suppliers.isPending ? (
                  /* Skeleton loader */
                  <div className="mt-3 space-y-2 animate-pulse">
                    {[...Array(8)].map((_, i) => (
                      <div key={i} className="flex items-center justify-between py-1">
                        <div className="h-3 w-32 rounded bg-surface" />
                        <div className="h-5 w-8 rounded-full bg-surface" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <ul className="mt-3 flex-1 divide-y divide-slate-100 overflow-y-auto">
                    {suppliers.data
                      ?.slice()
                      .sort((a, b) => b.riskScore - a.riskScore)
                      .map((s) => (
                        <li key={s.id} className="flex items-center justify-between py-2 pr-1">
                          <span className="truncate text-sm text-ink-2">{s.name}</span>
                          <span className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
                            s.riskScore >= 70 ? "bg-red-100 text-red-700"
                            : s.riskScore >= 40 ? "bg-amber-100 text-amber-700"
                            : "bg-green-100 text-green-700"
                          }`}>{s.riskScore}</span>
                        </li>
                      )) ?? <li className="py-2 text-sm text-ink-3">No data</li>}
                  </ul>
                )}
              </Card>
            </div>

            <div key="delays" data-grid={{ x: 0, y: 5, w: 12, h: 5, minW: 6, minH: 4 }}>
              <Card className="h-full">
                <CardTitle>
                  <span className="drag flex cursor-grab items-center gap-1.5 select-none">
                    <GripIcon />Shipment delays
                  </span>
                </CardTitle>
                {shipmentDelay.data
                  ? <LazyBarChart data={shipmentDelay.data} />
                  : <p className="mt-4 text-xs text-slate-400">No data available</p>}
              </Card>
            </div>
          </ResponsiveGridLayout>
        </>
      )}
    </div>
  );
}
