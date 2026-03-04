import { Card } from "@/design-system/components/card";
import { PageTitle } from "@/design-system/components/typography";

export function AdminPage() {
  return <div className="space-y-4"><PageTitle>Admin</PageTitle><Card><p className="text-sm">Role-based access policies, field-level masking rules, and audit controls.</p></Card></div>;
}
