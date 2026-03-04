"use client";

import { useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { Tabs } from "@/design-system/components/tabs";
import { DataTable } from "@/design-system/components/data-table";
import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { RiskScoreBadge } from "@/design-system/components/status-badges";
import { suppliers } from "@/services/mockData";

const profileTabs = ["Overview", "Risk", "Performance", "Shipments", "Documents", "Alerts"];

export function SuppliersPage() {
  const [active, setActive] = useState(profileTabs[0]);
  const columns = useMemo<ColumnDef<(typeof suppliers)[number]>[]>(() => [
    { header: "ID", accessorKey: "id" },
    { header: "Name", accessorKey: "name" },
    { header: "Region", accessorKey: "region" },
    { header: "Risk", cell: ({ row }) => <RiskScoreBadge score={row.original.riskScore} /> },
    { header: "Spend", accessorKey: "spend" }
  ], []);

  return (
    <div className="space-y-4">
      <PageTitle>Supplier Profiles</PageTitle>
      <Card><DataTable data={suppliers} columns={columns} /></Card>
      <Card>
        <Tabs tabs={profileTabs} active={active} onSelect={setActive} />
        <div className="mt-4 text-sm">
          {active === "Overview" && <div className="grid grid-cols-2 gap-4"><p>Risk score: 82</p><p>Spend: $1.2M</p><p>Active POs: 47</p><p>Certifications: ISO 9001, ESG-A</p></div>}
          {active === "Risk" && <p>Risk factors: weather volatility, credit rating pressure, transport disruption exposure.</p>}
          {active === "Performance" && <p>On-time delivery: 92%, quality yield: 98.1%.</p>}
          {active === "Shipments" && <p>27 in-transit shipments, 4 delayed.</p>}
          {active === "Documents" && <p>34 contracts, 12 audit records.</p>}
          {active === "Alerts" && <p>3 unresolved alerts and 8 resolved in last 30 days.</p>}
        </div>
      </Card>
    </div>
  );
}
