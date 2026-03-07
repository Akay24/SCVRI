"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/design-system/components/data-table";
import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { Modal } from "@/design-system/components/overlays";
import { shipmentService, type Shipment, type ShipmentDraft } from "@/services/shipmentService";
import { supplierService } from "@/services/supplierService";

const MODES:   Shipment["mode"][]   = ["SEA", "AIR", "RAIL", "ROAD"];
const STATUSES: Shipment["status"][] = ["on-track", "delayed", "at-risk"];

const inputCls = "w-full rounded-md border border-stroke bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none";

const EMPTY_DRAFT: ShipmentDraft = {
  supplier: "", origin: "", destination: "",
  mode: "SEA", status: "on-track",
  eta: new Date().toISOString().slice(0, 10),
  daysDelayed: 0, value: 100000, containers: 1,
};

function ShipmentForm({
  suppliers, initial, saving, onSave, onCancel,
}: {
  suppliers: { id: string; name: string }[];
  initial: ShipmentDraft;
  saving: boolean;
  onSave: (d: ShipmentDraft) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState<ShipmentDraft>(initial);
  const set = (k: keyof ShipmentDraft, v: string | number) => setF((p) => ({ ...p, [k]: v }));

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="mb-1 block text-xs font-medium text-ink-3">Supplier *</label>
          <select value={f.supplier} onChange={(e) => set("supplier", e.target.value)} className={inputCls}>
            <option value="">— select —</option>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.id} – {s.name}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Origin *</label>
          <input value={f.origin} onChange={(e) => set("origin", e.target.value)} className={inputCls} placeholder="e.g. Busan" />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Destination *</label>
          <input value={f.destination} onChange={(e) => set("destination", e.target.value)} className={inputCls} placeholder="e.g. Rotterdam" />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Mode</label>
          <select value={f.mode} onChange={(e) => set("mode", e.target.value)} className={inputCls}>
            {MODES.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Status</label>
          <select value={f.status} onChange={(e) => set("status", e.target.value)} className={inputCls}>
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">ETA</label>
          <input type="date" value={f.eta} onChange={(e) => set("eta", e.target.value)} className={inputCls} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Days delayed</label>
          <input type="number" min={0} value={f.daysDelayed} onChange={(e) => set("daysDelayed", Number(e.target.value))} className={inputCls} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Value ($)</label>
          <input type="number" min={0} value={f.value} onChange={(e) => set("value", Number(e.target.value))} className={inputCls} />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink-3">Containers</label>
          <input type="number" min={1} value={f.containers} onChange={(e) => set("containers", Number(e.target.value))} className={inputCls} />
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onCancel} className="rounded-md border border-stroke px-4 py-2 text-sm text-ink-2 hover:bg-surface">Cancel</button>
        <Button onClick={() => onSave(f)} disabled={saving || !f.supplier || !f.origin || !f.destination}>
          {saving ? "Saving…" : "Save shipment"}
        </Button>
      </div>
    </div>
  );
}

const STATUS_FILTER_ALL = ["all", ...STATUSES] as const;
type StatusFilter = (typeof STATUS_FILTER_ALL)[number];

export function ShipmentsPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [modalMode, setModalMode]       = useState<"add" | "edit" | null>(null);
  const [editTarget, setEditTarget]     = useState<Shipment | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const shipQ = useQuery({ queryKey: ["shipments"], queryFn: () => shipmentService.list() });
  const suppQ = useQuery({ queryKey: ["suppliers"], queryFn: supplierService.list });

  const allShipments = shipQ.data ?? [];
  const suppliers    = suppQ.data ?? [];

  const filtered = statusFilter === "all"
    ? allShipments
    : allShipments.filter((s) => s.status === statusFilter);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["shipments"] });

  const createMut = useMutation({
    mutationFn: shipmentService.create,
    onSuccess: () => { invalidate(); setModalMode(null); },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<ShipmentDraft> }) => shipmentService.update(id, patch),
    onSuccess: () => { invalidate(); setModalMode(null); setEditTarget(null); },
  });
  const deleteMut = useMutation({
    mutationFn: shipmentService.remove,
    onSuccess: () => { invalidate(); setDeleteTarget(null); },
  });

  const columns = useMemo<ColumnDef<Shipment>[]>(() => [
    { header: "ID",          accessorKey: "id",          size: 100 },
    { header: "Supplier",    accessorKey: "supplier",    size: 100 },
    { header: "Origin",      accessorKey: "origin" },
    { header: "Destination", accessorKey: "destination" },
    { header: "Mode",        accessorKey: "mode",        size: 70 },
    {
      header: "Status",
      size: 100,
      cell: ({ row }) => (
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
          row.original.status === "delayed"  ? "bg-red-100 text-red-700"
          : row.original.status === "at-risk" ? "bg-amber-100 text-amber-700"
          : "bg-emerald-100 text-emerald-700"
        }`}>{row.original.status}</span>
      ),
    },
    {
      header: "ETA",
      cell: ({ row }) => (
        <span className="text-ink-2">
          {row.original.eta}
          {row.original.daysDelayed > 0 && (
            <span className="ml-1 text-red-600 font-medium">(+{row.original.daysDelayed}d)</span>
          )}
        </span>
      ),
    },
    {
      header: "Value",
      cell: ({ row }) => <span className="text-ink-2">${(row.original.value / 1000).toFixed(0)}K</span>,
    },
    {
      header: "Actions",
      size: 110,
      cell: ({ row }) => (
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => { setEditTarget(row.original); setModalMode("edit"); }}
            className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10"
          >Edit</button>
          <button
            onClick={() => setDeleteTarget(row.original.id)}
            className="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
          >Delete</button>
        </div>
      ),
    },
  ], []);

  // KPI counts
  const delayed  = allShipments.filter((s) => s.status === "delayed").length;
  const atRisk   = allShipments.filter((s) => s.status === "at-risk").length;
  const onTrack  = allShipments.filter((s) => s.status === "on-track").length;
  const totalVal = allShipments.reduce((a, s) => a + s.value, 0);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <PageTitle>Shipment Visibility</PageTitle>
        <Button onClick={() => { setEditTarget(null); setModalMode("add"); }}>+ Add Shipment</Button>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Total shipments", value: String(allShipments.length) },
          { label: "On track",        value: String(onTrack),  cls: "text-emerald-600" },
          { label: "Delayed",         value: String(delayed),  cls: "text-red-600" },
          { label: "At risk",         value: String(atRisk),   cls: "text-amber-600" },
        ].map(({ label, value, cls }) => (
          <div key={label} className="rounded-xl border border-stroke bg-card p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wide text-ink-3">{label}</p>
            <p className={`mt-2 text-3xl font-bold tabular-nums ${cls ?? "text-ink"}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Status filters */}
      <div className="flex gap-1">
        {STATUS_FILTER_ALL.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors ${
              statusFilter === s ? "bg-accent text-white" : "bg-surface text-ink-2 hover:bg-stroke/40"
            }`}
          >{s === "all" ? `All (${allShipments.length})` : s}</button>
        ))}
      </div>

      {/* Table */}
      {shipQ.isLoading ? (
        <div className="h-48 animate-pulse rounded-lg bg-surface" />
      ) : (
        <Card className="p-0 overflow-hidden">
          <DataTable data={filtered} columns={columns} />
        </Card>
      )}

      {/* Add / Edit modal */}
      <Modal
        title={modalMode === "edit" ? `Edit — ${editTarget?.id ?? ""}` : "Add new shipment"}
        open={modalMode !== null}
        onClose={() => { setModalMode(null); setEditTarget(null); }}
      >
        <ShipmentForm
          suppliers={suppliers}
          initial={editTarget ?? EMPTY_DRAFT}
          saving={createMut.isPending || updateMut.isPending}
          onCancel={() => { setModalMode(null); setEditTarget(null); }}
          onSave={(draft) => {
            if (modalMode === "edit" && editTarget) {
              updateMut.mutate({ id: editTarget.id, patch: draft });
            } else {
              createMut.mutate(draft);
            }
          }}
        />
      </Modal>

      {/* Delete confirmation */}
      <Modal title="Delete shipment" open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <p className="text-sm text-ink-2">
          Permanently delete shipment <span className="font-semibold">{deleteTarget}</span>? This cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setDeleteTarget(null)} className="rounded-md border border-stroke px-4 py-2 text-sm text-ink-2 hover:bg-surface">Cancel</button>
          <button
            onClick={() => deleteTarget && deleteMut.mutate(deleteTarget)}
            disabled={deleteMut.isPending}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >{deleteMut.isPending ? "Deleting…" : "Delete"}</button>
        </div>
      </Modal>
    </div>
  );
}
