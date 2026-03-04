"use client";

import GridLayout from "react-grid-layout";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/design-system/components/card";
import { PageTitle, CardTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { LazyBarChart, LazyLineChart } from "@/components/charts/reusable-charts";
import { riskService } from "@/services/riskService";
import { shipmentService } from "@/services/shipmentService";
import { supplierService } from "@/services/supplierService";

export function DashboardPage() {
  const riskTrend = useQuery({ queryKey: ["risk-trend"], queryFn: riskService.trend });
  const shipmentDelay = useQuery({ queryKey: ["shipment-delay"], queryFn: shipmentService.delays });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: supplierService.list });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <PageTitle>Executive Dashboard</PageTitle>
        <div className="flex gap-2">
          <Button>7d</Button><Button className="bg-slate-600">30d</Button><Button className="bg-slate-600">90d</Button><Button>Export</Button>
        </div>
      </div>
      <GridLayout className="layout" cols={12} rowHeight={120} width={1200} draggableHandle=".drag">
        <div key="risk" data-grid={{ x: 0, y: 0, w: 6, h: 2 }}><Card><CardTitle><span className="drag">Risk heatmap</span></CardTitle>{riskTrend.data && <LazyLineChart data={riskTrend.data} />}</Card></div>
        <div key="atrisk" data-grid={{ x: 6, y: 0, w: 6, h: 2 }}><Card><CardTitle><span className="drag">Top at-risk suppliers</span></CardTitle><ul className="mt-3 text-sm">{suppliers.data?.map((s) => <li key={s.id}>{s.name} ({s.riskScore})</li>)}</ul></Card></div>
        <div key="disruptions" data-grid={{ x: 0, y: 2, w: 4, h: 2 }}><Card><CardTitle><span className="drag">Active disruptions</span></CardTitle><p className="mt-2 text-sm">12 open disruption events</p></Card></div>
        <div key="spend" data-grid={{ x: 4, y: 2, w: 4, h: 2 }}><Card><CardTitle><span className="drag">Spend at risk</span></CardTitle><p className="mt-2 text-sm">$4.2M exposed</p></Card></div>
        <div key="alerts" data-grid={{ x: 8, y: 2, w: 4, h: 2 }}><Card><CardTitle><span className="drag">Recent alerts</span></CardTitle><p className="mt-2 text-sm">5 critical in last 24h</p></Card></div>
        <div key="delays" data-grid={{ x: 0, y: 4, w: 12, h: 2 }}><Card><CardTitle><span className="drag">Shipment delays</span></CardTitle>{shipmentDelay.data && <LazyBarChart data={shipmentDelay.data} />}</Card></div>
      </GridLayout>
    </div>
  );
}
