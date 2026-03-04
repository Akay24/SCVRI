import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";
import { Button } from "@/design-system/components/button";
import { reportService } from "@/services/reportService";

export function ReportsPage() {
  return (
    <div className="space-y-4">
      <PageTitle>Reports & Analytics</PageTitle>
      <Card><h3 className="font-semibold">Prebuilt reports</h3><p className="text-sm">Spend concentration, supplier performance, risk trends, lead time trends.</p></Card>
      <Card><h3 className="font-semibold">Custom report builder</h3><p className="text-sm">Create metric slices by region, supplier tier, and category.</p></Card>
      <Card><h3 className="font-semibold">Scheduled exports</h3><div className="mt-2 flex gap-2">{reportService.formats.map((f) => <Button key={f}>{f}</Button>)}</div></Card>
    </div>
  );
}
