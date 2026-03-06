"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { alertService } from "@/services/alertService";
import { Card } from "@/design-system/components/card";
import { PageTitle, CardTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { AlertSeverityIndicator } from "@/design-system/components/status-badges";

const SEVERITIES = ["all", "critical", "high", "medium", "low"] as const;
const STATUSES   = ["all", "open", "acknowledged", "resolved"] as const;

type Severity = (typeof SEVERITIES)[number];
type Status   = (typeof STATUSES)[number];

// Local state: per-alert status overrides + per-alert notes
type LocalState = Record<string, { status: Status; notes: string }>;

export function AlertsPage() {
  const queryClient = useQueryClient();
  const [severityFilter, setSeverityFilter] = useState<Severity>("all");
  const [statusFilter,   setStatusFilter]   = useState<Status>("all");
  const [local, setLocal] = useState<LocalState>({});

  const { data: alerts = [], isPending, isError } = useQuery({
    queryKey: ["alerts"],
    queryFn: alertService.list,
  });

  const ackMutation = useMutation({
    mutationFn: (id: string) => alertService.acknowledge(id),
    onSuccess: (res) => {
      setLocal((prev) => ({
        ...prev,
        [res.id]: { ...prev[res.id], status: "acknowledged", notes: prev[res.id]?.notes ?? "" },
      }));
    },
  });

  function setAlertStatus(id: string, status: Status) {
    setLocal((prev) => ({ ...prev, [id]: { ...prev[id], status, notes: prev[id]?.notes ?? "" } }));
  }

  function setAlertNotes(id: string, notes: string) {
    setLocal((prev) => ({ ...prev, [id]: { ...prev[id], notes, status: prev[id]?.status ?? "open" } }));
  }

  const filtered = alerts.filter((a) => {
    const effectiveStatus = local[a.id]?.status ?? a.status;
    const matchSev = severityFilter === "all" || a.severity === severityFilter;
    const matchSta = statusFilter   === "all" || effectiveStatus === statusFilter;
    return matchSev && matchSta;
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <PageTitle>Alert Center</PageTitle>
        <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700">
          {alerts.filter((a) => (local[a.id]?.status ?? a.status) === "open").length} open
        </span>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-6">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-3">Severity</p>
          <div className="flex gap-1">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                onClick={() => setSeverityFilter(s)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
                  severityFilter === s
                    ? "bg-accent text-white"
                    : "bg-surface text-ink-2 hover:bg-stroke/40"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-3">Status</p>
          <div className="flex gap-1">
            {STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
                  statusFilter === s
                    ? "bg-accent text-white"
                    : "bg-surface text-ink-2 hover:bg-stroke/40"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      {isPending && (
        <div className="space-y-3 animate-pulse">
          {[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-xl bg-surface" />)}
        </div>
      )}
      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load alerts.
        </div>
      )}

      {!isPending && filtered.length === 0 && (
        <Card><p className="text-sm text-slate-400">No alerts match the selected filters.</p></Card>
      )}

      <div className="space-y-3">
        {filtered.map((alert) => {
          const effectiveStatus = local[alert.id]?.status ?? alert.status;
          const notes = local[alert.id]?.notes ?? "";
          const isResolved = effectiveStatus === "resolved";

          return (
            <Card
              key={alert.id}
              className={`transition-opacity ${isResolved ? "opacity-50" : ""}`}
            >
              {/* Title row */}
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-800">{alert.title}</p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {alert.id} · assigned to <span className="font-medium text-slate-600">{alert.assignedTo}</span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <AlertSeverityIndicator severity={alert.severity} />
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                    effectiveStatus === "open"         ? "bg-orange-100 text-orange-700"
                    : effectiveStatus === "acknowledged" ? "bg-accent/10 text-accent"
                    : "bg-green-100 text-green-700"
                  }`}>{effectiveStatus}</span>
                </div>
              </div>

              {/* Actions */}
              {!isResolved && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {effectiveStatus === "open" && (
                    <Button
                      onClick={() => ackMutation.mutate(alert.id)}
                      disabled={ackMutation.isPending}
                    >
                      {ackMutation.isPending ? "Acknowledging…" : "Acknowledge"}
                    </Button>
                  )}
                  <Button onClick={() => setAlertStatus(alert.id, "resolved")}>
                    Resolve
                  </Button>
                </div>
              )}

              {/* Per-alert notes */}
              <textarea
                value={notes}
                onChange={(e) => setAlertNotes(alert.id, e.target.value)}
                aria-label={`Notes for ${alert.id}`}
                placeholder="Add resolution notes…"
                rows={2}
                className="mt-3 w-full rounded-md border border-stroke bg-surface px-3 py-2 text-xs text-ink focus:border-accent focus:outline-none transition-colors"
              />
            </Card>
          );
        })}
      </div>
    </div>
  );
}
