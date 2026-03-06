"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { LazyLineChart, LazyBarChart } from "@/components/charts/reusable-charts";
import { riskService } from "@/services/riskService";
import { suppliers, riskEvents } from "@/services/mockData";
import { RiskScoreBadge } from "@/design-system/components/status-badges";

const TYPE_COLOR: Record<string, string> = {
  weather:      "bg-brand-powder/30 text-brand-dark",
  geopolitical: "bg-accent/10 text-accent",
  transport:    "bg-[#964734]/10 text-[#964734]",
  financial:    "bg-red-100 text-red-700",
  esg:          "bg-emerald-100 text-emerald-700",
  capacity:     "bg-amber-100 text-amber-700",
};

function StatCard({ label, value, sub, danger }: { label: string; value: string; sub?: string; danger?: boolean }) {
  return (
    <div className="rounded-xl border border-stroke bg-card p-5 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
      <p className={`mt-2 text-3xl font-bold tabular-nums ${danger ? "text-red-600" : "text-ink"}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-ink-3">{sub}</p>}
    </div>
  );
}

export function RiskIntelligencePage() {
  const trend    = useQuery({ queryKey: ["risk-trend"],  queryFn: riskService.trend    });
  const byRegion = useQuery({ queryKey: ["risk-region"], queryFn: riskService.byRegion });
  const byDriver = useQuery({ queryKey: ["risk-driver"], queryFn: riskService.byDriver });

  const ranked = [...suppliers].sort((a, b) => b.riskScore - a.riskScore);
  const criticalCount = riskEvents.filter((e) => e.severityScore >= 70).length;

  return (
    <div className="space-y-6">
      <PageTitle>Risk Intelligence</PageTitle>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Platform risk score"  value="67"  sub="composite this week"    danger />
        <StatCard label="Critical events"       value={String(criticalCount)} sub="last 30 days" danger />
        <StatCard label="High-risk suppliers"   value={String(suppliers.filter((s) => s.riskScore >= 70).length)} sub="score ≥ 70" />
        <StatCard label="Spend exposed"         value="$9.1M" sub="at-risk suppliers" />
      </div>

      {/* Charts row */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <p className="mb-3 font-semibold text-ink-2">13-week risk score trend</p>
            {trend.data ? <LazyLineChart data={trend.data} /> : <div className="h-40 animate-pulse rounded bg-surface" />}
          </Card>
        </div>
        <Card>
          <p className="mb-3 font-semibold text-ink-2">Risk by region</p>
          {byRegion.data ? <LazyBarChart data={byRegion.data} /> : <div className="h-40 animate-pulse rounded bg-surface" />}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Risk by driver */}
        <Card>
          <p className="mb-4 font-semibold text-ink-2">Risk contribution by driver</p>
          {byDriver.data ? (
            <div className="space-y-3">
              {byDriver.data.map((d) => (
                <div key={d.name}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-ink-3">{d.name}</span>
                    <span className="font-semibold text-ink-2">{d.value}%</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-stroke/60">
                    <div
                      className={`h-2 rounded-full ${
                        d.value >= 25 ? "bg-red-400" : d.value >= 15 ? "bg-amber-400" : "bg-emerald-400"
                      }`}
                      style={{ width: `${d.value * 3.5}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="h-40 animate-pulse rounded bg-surface" />}
        </Card>

        {/* Supplier risk ranking */}
        <Card>
          <p className="mb-4 font-semibold text-ink-2">Supplier risk ranking</p>
          <div className="space-y-2">
            {ranked.slice(0, 8).map((s, i) => (
              <div key={s.id} className="flex items-center justify-between rounded-lg bg-surface px-3 py-2">
                <div className="flex items-center gap-3">
                  <span className="w-5 text-xs font-bold text-ink-3">#{i + 1}</span>
                  <div>
                    <p className="text-sm font-medium text-ink-2">{s.name}</p>
                    <p className="text-xs text-ink-3">{s.country} · {s.category}</p>
                  </div>
                </div>
                <RiskScoreBadge score={s.riskScore} />
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Risk event timeline */}
      <Card>
          <p className="mb-4 font-semibold text-ink-2">Risk event timeline</p>
          <div className="space-y-2">
            {riskEvents.map((e) => (
              <div key={e.date + e.title} className="flex items-start gap-4 rounded-lg border border-stroke bg-surface px-4 py-3">
                <span className="mt-0.5 shrink-0 text-xs font-mono text-ink-3">{e.date}</span>
                <div className="flex-1">
                  <p className="text-sm font-medium text-ink-2">{e.title}</p>
                  <p className="text-xs text-ink-3">
                    {e.impactedSuppliers} supplier{e.impactedSuppliers !== 1 ? "s" : ""} affected · {e.region}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${TYPE_COLOR[e.type] ?? "bg-surface text-ink-2"}`}>
                  {e.type}
                </span>
                <span className={`text-xs font-bold ${
                  e.severityScore >= 70 ? "text-red-600" : e.severityScore >= 50 ? "text-amber-600" : "text-slate-500"
                }`}>{e.severityScore}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
