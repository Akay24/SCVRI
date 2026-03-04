import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { LazyLineChart, LazyBarChart } from "@/components/charts/reusable-charts";

const geoRisk = [{ name: "NA", value: 34 }, { name: "EMEA", value: 48 }, { name: "APAC", value: 67 }];
const trend = [{ name: "Jan", value: 46 }, { name: "Feb", value: 53 }, { name: "Mar", value: 59 }];

export function RiskIntelligencePage() {
  return (
    <div className="space-y-4">
      <PageTitle>Risk Intelligence</PageTitle>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><h3 className="font-semibold">Risk heatmap by geography</h3><LazyBarChart data={geoRisk} /></Card>
        <Card><h3 className="font-semibold">Risk trend</h3><LazyLineChart data={trend} /></Card>
      </div>
      <Card><h3 className="font-semibold">Supplier risk ranking</h3><p className="text-sm">1. Orion Metals (82), 2. Delta Components (78), 3. Arc Semiconductors (75)</p></Card>
      <Card><h3 className="font-semibold">Risk event timeline</h3><p className="text-sm">Events tagged with weather, geopolitical, financial, ESG, transport contributors.</p></Card>
    </div>
  );
}
