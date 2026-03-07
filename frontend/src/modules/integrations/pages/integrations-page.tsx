import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";

export function IntegrationsPage() {
  return <div className="space-y-4"><PageTitle>Integrations</PageTitle><Card><p className="text-sm">Manage ERP, carrier, webhook, Slack, and PagerDuty connectors with credential masking and RBAC.</p></Card></div>;
}
