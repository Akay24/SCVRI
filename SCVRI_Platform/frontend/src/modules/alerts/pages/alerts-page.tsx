"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { alertService, type AlertDraft } from "@/services/alertService";
import { supplierService } from "@/services/supplierService";
import { Card } from "@/design-system/components/card";
import { PageTitle, CardTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { Modal } from "@/design-system/components/overlays";
import { AlertSeverityIndicator } from "@/design-system/components/status-badges";

const SEVERITIES      = ["all", "critical", "high", "medium", "low"] as const;
const STATUSES        = ["all", "open", "acknowledged", "resolved"] as const;
const ALERT_CATEGORIES = ["weather", "financial", "geopolitical", "transport", "esg", "capacity", "performance"];
const REGIONS         = ["AMER", "EU", "EMEA", "APAC"];

type Severity = (typeof SEVERITIES)[number];
type Status   = (typeof STATUSES)[number];
type LocalState = Record<string, { status: Status; notes: string }>;

const inputCls = "w-full rounded-md border border-stroke bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none";

const EMPTY_DRAFT: AlertDraft = {
  title: "", severity: "medium", category: "transport",
  supplier: "", assignedTo: "", region: "APAC",
};

function AlertForm({
  suppliers, initial, saving, onSave, onCancel,
}: {
  suppliers: { id: string; name: string }[];
  initial: AlertDraft;
  saving: boolean;
  onSave: (d: AlertDraft) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState<AlertDraft>(initial);
  const set = (k: keyof AlertDraft, v: string) => setF((p) => ({ ...p, [k]: v }));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="mb-1 block text-xs font-medium text-ink-3">Alert title *</label>
          <input value={f.title} onChange={(e) => set("title", e.target.value)}
            className={inputCls} placeholder="Describe the risk event…" />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Severity</label>
          <select value={f.severity} onChange={(e) => set("severity", e.target.value)} className={inputCls}>
            {["critical","high","medium","low"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Category</label>
          <select value={f.category} onChange={(e) => set("category", e.target.value)} className={inputCls}>
            {ALERT_CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Supplier</label>
          <select value={f.supplier} onChange={(e) => set("supplier", e.target.value)} className={inputCls}>
            <option value="">— none —</option>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.id} – {s.name}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Region</label>
          <select value={f.region} onChange={(e) => set("region", e.target.value)} className={inputCls}>
            {REGIONS.map((r) => <option key={r}>{r}</option>)}
          </select>
        </div>
        <div className="col-span-2">
          <label className="mb-1 block text-xs font-medium text-ink-3">Assigned to</label>
          <input value={f.assignedTo} onChange={(e) => set("assignedTo", e.target.value)}
            className={inputCls} placeholder="e.g. Ops Team" />
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onCancel} className="rounded-md border border-stroke px-4 py-2 text-sm text-ink-2 hover:bg-surface">Cancel</button>
        <Button onClick={() => onSave(f)} disabled={saving || !f.title}>
          {saving ? "Creating…" : "Create alert"}
        </Button>
      </div>
    </div>
  );
}

export function AlertsPage() {
  const queryClient = useQueryClient();
  const [severityFilter, setSeverityFilter] = useState<Severity>("all");
  const [statusFilter,   setStatusFilter]   = useState<Status>("all");
  const [local, setLocal] = useState<LocalState>({});
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const { data: alerts = [], isPending, isError } = useQuery({
    queryKey: ["alerts"],
    queryFn: () => alertService.list(),
  });
  const { data: supplierList = [] } = useQuery({
    queryKey: ["suppliers"],
    queryFn: supplierService.list,
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

  const createMutation = useMutation({
    mutationFn: (draft: AlertDraft) => alertService.create(draft),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["alerts"] }); setShowCreate(false); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => alertService.remove(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["alerts"] }); setDeleteTarget(null); },
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
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700">
            {alerts.filter((a) => (local[a.id]?.status ?? a.status) === "open").length} open
          </span>
          <Button onClick={() => setShowCreate(true)}>+ Create Alert</Button>
        </div>
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
                  <p className="text-sm font-semibold text-ink">{alert.title}</p>
                  <p className="mt-0.5 text-xs text-ink-3">
                    {alert.id} · assigned to <span className="font-medium text-ink-2">{alert.assignedTo}</span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <AlertSeverityIndicator severity={alert.severity} />
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                    effectiveStatus === "open"         ? "bg-orange-100 text-orange-700"
                    : effectiveStatus === "acknowledged" ? "bg-accent/10 text-accent"
                    : "bg-green-100 text-green-700"
                  }`}>{effectiveStatus}</span>
                  <button
                    onClick={() => setDeleteTarget(alert.id)}
                    className="ml-1 rounded p-1 text-ink-3 hover:bg-red-50 hover:text-red-600"
                    aria-label="Delete alert"
                  >
                    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M2 4h12M6 4V2h4v2M5 4l1 10h4l1-10" />
                    </svg>
                  </button>
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

      {/* Create Alert modal */}
      <Modal title="Create new alert" open={showCreate} onClose={() => setShowCreate(false)}>
        <AlertForm
          suppliers={supplierList}
          initial={EMPTY_DRAFT}
          saving={createMutation.isPending}
          onCancel={() => setShowCreate(false)}
          onSave={(draft) => createMutation.mutate(draft)}
        />
      </Modal>

      {/* Delete confirmation */}
      <Modal title="Delete alert" open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <p className="text-sm text-ink-2">
          Permanently delete alert <span className="font-semibold">{deleteTarget}</span>? This cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setDeleteTarget(null)} className="rounded-md border border-stroke px-4 py-2 text-sm text-ink-2 hover:bg-surface">Cancel</button>
          <button
            onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
            disabled={deleteMutation.isPending}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >{deleteMutation.isPending ? "Deleting…" : "Delete"}</button>
        </div>
      </Modal>
    </div>
  );
}
