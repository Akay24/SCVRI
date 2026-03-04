export const suppliers = [
  { id: "SUP-001", name: "Orion Metals", riskScore: 82, spend: 1200000, activePOs: 47, region: "EMEA" },
  { id: "SUP-002", name: "Pacific Circuits", riskScore: 39, spend: 850000, activePOs: 23, region: "APAC" },
  { id: "SUP-003", name: "Nordic Plastics", riskScore: 66, spend: 460000, activePOs: 18, region: "EU" }
];

export const alerts = [
  { id: "AL-1001", title: "Cyclone impact near Chennai", severity: "critical", status: "open", assignedTo: "Ops Team" },
  { id: "AL-1002", title: "Supplier liquidity downgrade", severity: "high", status: "acknowledged", assignedTo: "Risk Analyst" }
] as const;
