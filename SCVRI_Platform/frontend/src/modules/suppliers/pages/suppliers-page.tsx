"use client";

import { useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { Tabs } from "@/design-system/components/tabs";
import { DataTable } from "@/design-system/components/data-table";
import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { RiskScoreBadge } from "@/design-system/components/status-badges";
import { suppliers, alerts, shipments } from "@/services/mockData";

const profileTabs = ["Overview", "Risk", "Performance", "Shipments", "Documents", "Alerts"];

function fmt(n: number) {
  return n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(1)}M`
    : `$${(n / 1_000).toFixed(0)}K`;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-stroke bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
      <p className="mt-1 text-2xl font-bold text-ink">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-3">{sub}</p>}
    </div>
  );
}

function Bar({ pct, color = "bg-accent" }: { pct: number; color?: string }) {
  return (
    <div className="h-2 w-full rounded-full bg-stroke/60">
      <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function SuppliersPage() {
  const [active, setActive] = useState(profileTabs[0]);
  const [selectedId, setSelectedId] = useState(suppliers[0].id);

  const s = suppliers.find((x) => x.id === selectedId) ?? suppliers[0];
  const supplierAlerts = alerts.filter((a) => a.supplier === s.id);
  const supplierShipments = shipments.filter((sh) => sh.supplier === s.id);

  const columns = useMemo<ColumnDef<(typeof suppliers)[number]>[]>(
    () => [
      { header: "ID",      accessorKey: "id",             size: 90 },
      { header: "Supplier",accessorKey: "name" },
      { header: "Country", accessorKey: "country" },
      { header: "Tier",    accessorKey: "tier",           size: 60 },
      { header: "Category",accessorKey: "category" },
      { header: "Risk",    cell: ({ row }) => <RiskScoreBadge score={row.original.riskScore} /> },
      { header: "Spend",   cell: ({ row }) => fmt(row.original.spend) },
      { header: "OTD %",   cell: ({ row }) => (
        <span className={row.original.onTimeDelivery < 85 ? "font-semibold text-red-600" : "text-ink-2"}>
          {row.original.onTimeDelivery}%
        </span>
      )},
    ],
    []
  );

  return (
    <div className="space-y-5">
      <PageTitle>Supplier Profiles</PageTitle>

      <Card className="p-0 overflow-hidden">
        <div onClick={(e) => {
          const row = (e.target as HTMLElement).closest("tr");
          if (row) {
            const id = row.querySelector("td")?.textContent?.trim();
            if (id) setSelectedId(id);
          }
        }}>
          <DataTable data={suppliers} columns={columns} />
        </div>
      </Card>

      {/* Detail panel for selected supplier */}
      <Card>
        <div className="mb-4 flex items-start justify-between">
          <div>
            <p className="text-lg font-bold text-ink">{s.name}</p>
            <p className="text-xs text-ink-3">{s.id} · {s.country} · {s.region} · Tier {s.tier}</p>
          </div>
          <RiskScoreBadge score={s.riskScore} />
        </div>
        <Tabs tabs={profileTabs} active={active} onSelect={setActive} />
        <div className="mt-5">

          {active === "Overview" && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Kpi label="Annual Spend"   value={fmt(s.spend)}         sub="last 12 months" />
              <Kpi label="Active POs"     value={String(s.activePOs)}  sub="open orders" />
              <Kpi label="Risk Score"     value={String(s.riskScore)}  sub="/ 100" />
              <Kpi label="Category"       value={s.category} />
            </div>
          )}

          {active === "Risk" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Kpi label="Risk Score"       value={String(s.riskScore)} sub="composite" />
                <Kpi label="Active alerts"    value={String(supplierAlerts.filter((a) => a.status !== "resolved").length)} />
                <Kpi label="Delayed shipments"value={String(s.delayed)} />
              </div>
              <div className="space-y-3 text-sm">
                {(["Financial", "Transport", "Geopolitical", "Weather", "ESG"] as const).map((driver, i) => {
                  const scores = [62, 45, 38, 71, 29];
                  return (
                    <div key={driver}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="text-ink-3">{driver}</span>
                        <span className="font-semibold text-ink-2">{scores[i]}</span>
                      </div>
                      <Bar pct={scores[i]} color={scores[i] > 60 ? "bg-red-400" : scores[i] > 40 ? "bg-amber-400" : "bg-emerald-400"} />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {active === "Performance" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Kpi label="On-time delivery" value={`${s.onTimeDelivery}%`} sub={s.onTimeDelivery < 85 ? "⚠️ Below 85% SLA" : "✓ SLA met"} />
                <Kpi label="Quality yield"    value={`${s.qualityYield}%`}   sub="acceptance rate" />
                <Kpi label="Avg lead time"    value="18 days"               sub="last quarter" />
                <Kpi label="SLA breaches"     value={s.onTimeDelivery < 85 ? "2" : "0"}  sub="last 30 days" />
              </div>
              <div className="space-y-3">
                {["Q3 2025", "Q4 2025", "Q1 2026"].map((q, i) => {
                  const vals = [s.onTimeDelivery - 4, s.onTimeDelivery - 2, s.onTimeDelivery];
                  return (
                    <div key={q}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="text-ink-3">{q} OTD</span>
                        <span className="font-medium">{vals[i]}%</span>
                      </div>
                      <Bar pct={vals[i]} color="bg-accent" />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {active === "Shipments" && (
            supplierShipments.length === 0
              ? <p className="text-sm text-ink-3">No active shipments for this supplier.</p>
              : <div className="space-y-2">
                  {supplierShipments.map((sh) => (
                    <div key={sh.id} className="flex items-center justify-between rounded-lg border border-stroke bg-surface px-4 py-3 text-sm">
                      <div>
                        <p className="font-semibold text-ink">{sh.id}</p>
                        <p className="text-xs text-ink-3">{sh.origin} → {sh.destination} · {sh.mode}</p>
                      </div>
                      <div className="text-right">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          sh.status === "delayed"  ? "bg-red-100 text-red-700"
                          : sh.status === "at-risk" ? "bg-amber-100 text-amber-700"
                          : "bg-emerald-100 text-emerald-700"
                        }`}>{sh.status}</span>
                        <p className="mt-0.5 text-xs text-ink-3">ETA {sh.eta}{sh.daysDelayed > 0 ? ` (+${sh.daysDelayed}d)` : ""}</p>
                      </div>
                    </div>
                  ))}
                </div>
          )}

          {active === "Documents" && (
            <div className="space-y-2 text-sm">
              {[
                { type: "Contract",          name: "Master Supply Agreement", date: "2024-01-15", status: "Active" },
                { type: "Audit",             name: "ISO 9001 Audit Report",   date: "2025-11-20", status: "Passed" },
                { type: "Certification",     name: "ESG Compliance Report",   date: "2025-09-30", status: "Valid" },
                { type: "Insurance",         name: "Cargo Insurance Policy",  date: "2025-12-31", status: "Active" },
              ].map((doc) => (
                <div key={doc.name} className="flex items-center justify-between rounded-lg border border-stroke bg-surface px-4 py-3">
                  <div>
                    <p className="font-medium text-ink-2">{doc.name}</p>
                    <p className="text-xs text-ink-3">{doc.type} · {doc.date}</p>
                  </div>
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">{doc.status}</span>
                </div>
              ))}
            </div>
          )}

          {active === "Alerts" && (
            supplierAlerts.length === 0
              ? <p className="text-sm text-ink-3">No alerts for this supplier.</p>
              : <div className="space-y-2">
                  {supplierAlerts.map((a) => (
                    <div key={a.id} className="flex items-center justify-between rounded-lg border border-stroke bg-surface px-4 py-3 text-sm">
                      <div>
                        <p className="font-medium text-ink-2">{a.title}</p>
                        <p className="text-xs text-ink-3">{a.id} · {a.category} · {a.createdAt.slice(0, 10)}</p>
                      </div>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${
                        a.severity === "critical" ? "bg-red-100 text-red-700"
                        : a.severity === "high"   ? "bg-orange-100 text-orange-700"
                        : a.severity === "medium" ? "bg-amber-100 text-amber-700"
                        : "bg-surface text-ink-2"
                      }`}>{a.severity}</span>
                    </div>
                  ))}
                </div>
          )}
        </div>
      </Card>
    </div>
  );
}
