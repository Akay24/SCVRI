"use client";

import { useState } from "react";
import { alerts } from "@/services/mockData";
import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { AlertSeverityIndicator } from "@/design-system/components/status-badges";
import { Filters } from "@/design-system/components/inputs";

export function AlertsPage() {
  const [notes, setNotes] = useState("");
  return (
    <div className="space-y-4">
      <PageTitle>Alert Center</PageTitle>
      <Filters><Button className="bg-slate-600">critical</Button><Button className="bg-slate-600">high</Button><Button className="bg-slate-600">open</Button></Filters>
      <Card>
        {alerts.map((alert) => (
          <div key={alert.id} className="mb-3 rounded border p-3 text-sm">
            <div className="flex items-center justify-between"><div className="font-medium">{alert.title}</div><AlertSeverityIndicator severity={alert.severity} /></div>
            <div className="mt-2 flex gap-2"><Button>Acknowledge</Button><Button>Assign</Button><Button>Resolve</Button></div>
            <p className="mt-2 text-xs">Audit trail: created 2h ago • assigned to {alert.assignedTo}</p>
          </div>
        ))}
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} aria-label="Resolution notes" className="w-full rounded border p-2 text-sm" placeholder="Add resolution notes" />
      </Card>
    </div>
  );
}
