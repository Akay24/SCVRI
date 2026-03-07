import { cn } from "@/utils/cn";

const severityColor: Record<string, string> = {
  low: "bg-risk-low/10 text-risk-low",
  medium: "bg-risk-medium/10 text-risk-medium",
  high: "bg-risk-high/10 text-risk-high",
  critical: "bg-risk-high text-white",
  neutral: "bg-risk-neutral/10 text-risk-neutral",
  inactive: "bg-risk-inactive/10 text-risk-inactive"
};

export function StatusBadge({ status }: { status: keyof typeof severityColor }) {
  return <span className={cn("rounded-full px-2 py-1 text-xs font-medium capitalize", severityColor[status])}>{status}</span>;
}

export const AlertSeverityIndicator = ({ severity }: { severity: "critical" | "high" | "medium" | "low" }) => (
  <StatusBadge status={severity} />
);

export function RiskScoreBadge({ score }: { score: number }) {
  const level = score > 75 ? "high" : score > 40 ? "medium" : "low";
  return <StatusBadge status={level} />;
}
