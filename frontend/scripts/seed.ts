/**
 * MongoDB Seed Script — SCVRI Platform
 * Seeds: suppliers, alerts, shipments, risk_events, risk_metrics, reports
 *
 * Run:  npx tsx scripts/seed.ts
 */
import { MongoClient } from "mongodb";

const MONGODB_URI =
  process.env.MONGODB_URI ||
  "mongodb://localhost:27017/SCVRI";

const DB_NAME = process.env.MONGODB_DB || "SCVRI";

// ─── Data ────────────────────────────────────────────────────────────────────

const suppliers = [
  { id: "SUP-001", name: "Orion Metals",           riskScore: 82, spend: 4_200_000, activePOs: 47, region: "EMEA", tier: 1, category: "Raw Materials",   onTimeDelivery: 78, qualityYield: 94.2, inTransit: 14, delayed: 4, country: "India" },
  { id: "SUP-002", name: "Pacific Circuits",        riskScore: 39, spend: 3_100_000, activePOs: 23, region: "APAC", tier: 1, category: "Electronics",    onTimeDelivery: 97, qualityYield: 99.1, inTransit: 9,  delayed: 0, country: "Taiwan" },
  { id: "SUP-003", name: "Nordic Plastics",         riskScore: 66, spend: 1_640_000, activePOs: 18, region: "EU",   tier: 2, category: "Packaging",      onTimeDelivery: 88, qualityYield: 97.3, inTransit: 6,  delayed: 1, country: "Sweden" },
  { id: "SUP-004", name: "Delta Components",        riskScore: 78, spend: 2_950_000, activePOs: 31, region: "EMEA", tier: 1, category: "Electronics",    onTimeDelivery: 81, qualityYield: 95.8, inTransit: 11, delayed: 3, country: "Germany" },
  { id: "SUP-005", name: "Arc Semiconductors",      riskScore: 75, spend: 5_800_000, activePOs: 62, region: "APAC", tier: 1, category: "Semiconductors", onTimeDelivery: 84, qualityYield: 96.4, inTransit: 22, delayed: 5, country: "South Korea" },
  { id: "SUP-006", name: "Apex Logistics",          riskScore: 44, spend: 980_000,   activePOs: 9,  region: "AMER", tier: 3, category: "Logistics",      onTimeDelivery: 93, qualityYield: 98.7, inTransit: 4,  delayed: 0, country: "USA" },
  { id: "SUP-007", name: "Bright Forge Industries", riskScore: 71, spend: 2_100_000, activePOs: 28, region: "APAC", tier: 2, category: "Metal Casting",  onTimeDelivery: 85, qualityYield: 96.0, inTransit: 10, delayed: 2, country: "China" },
  { id: "SUP-008", name: "Cascadia Timber",         riskScore: 29, spend: 740_000,   activePOs: 14, region: "AMER", tier: 3, category: "Raw Materials",   onTimeDelivery: 95, qualityYield: 99.4, inTransit: 5,  delayed: 0, country: "Canada" },
  { id: "SUP-009", name: "MediPack Solutions",      riskScore: 55, spend: 1_380_000, activePOs: 20, region: "EU",   tier: 2, category: "Packaging",      onTimeDelivery: 90, qualityYield: 97.8, inTransit: 7,  delayed: 1, country: "Netherlands" },
  { id: "SUP-010", name: "SolarEdge Materials",     riskScore: 61, spend: 3_430_000, activePOs: 38, region: "EMEA", tier: 1, category: "Semiconductors", onTimeDelivery: 87, qualityYield: 95.1, inTransit: 13, delayed: 2, country: "Israel" },
  { id: "SUP-011", name: "Sahara Textiles",         riskScore: 88, spend: 870_000,   activePOs: 16, region: "EMEA", tier: 2, category: "Textiles",       onTimeDelivery: 72, qualityYield: 91.3, inTransit: 5,  delayed: 3, country: "Egypt" },
  { id: "SUP-012", name: "Coastal Composites",      riskScore: 47, spend: 1_920_000, activePOs: 25, region: "AMER", tier: 2, category: "Raw Materials",   onTimeDelivery: 91, qualityYield: 98.2, inTransit: 8,  delayed: 1, country: "Mexico" },
];

const alerts = [
  { id: "AL-1001", title: "Cyclone impact near Chennai port — Tier 1 supplier affected",        severity: "critical", status: "open",         assignedTo: "Ops Team",      category: "weather",      supplier: "SUP-001", createdAt: "2026-03-06T04:15:00Z", region: "APAC" },
  { id: "AL-1002", title: "Orion Metals liquidity downgrade — credit rating cut to B−",         severity: "high",     status: "acknowledged", assignedTo: "Risk Analyst",  category: "financial",    supplier: "SUP-001", createdAt: "2026-03-05T11:30:00Z", region: "EMEA" },
  { id: "AL-1003", title: "Arc Semiconductors: export control review initiated by regulators",  severity: "high",     status: "open",         assignedTo: "Legal Team",    category: "geopolitical", supplier: "SUP-005", createdAt: "2026-03-05T08:00:00Z", region: "APAC" },
  { id: "AL-1004", title: "Delta Components: 3 shipments overdue >10 days on Hamburg lane",    severity: "high",     status: "open",         assignedTo: "Logistics",     category: "transport",    supplier: "SUP-004", createdAt: "2026-03-04T16:45:00Z", region: "EMEA" },
  { id: "AL-1005", title: "Bright Forge Industries: factory audited — 2 major ESG findings",   severity: "medium",   status: "open",         assignedTo: "Compliance",    category: "esg",          supplier: "SUP-007", createdAt: "2026-03-04T09:20:00Z", region: "APAC" },
  { id: "AL-1006", title: "Sahara Textiles: on-time delivery dropped to 72% — SLA breach",     severity: "high",     status: "acknowledged", assignedTo: "Supplier Mgmt", category: "performance",  supplier: "SUP-011", createdAt: "2026-03-03T14:00:00Z", region: "EMEA" },
  { id: "AL-1007", title: "SolarEdge Materials: port strike in Haifa delays 2 containers",     severity: "medium",   status: "open",         assignedTo: "Ops Team",      category: "transport",    supplier: "SUP-010", createdAt: "2026-03-03T07:30:00Z", region: "EMEA" },
  { id: "AL-1008", title: "Nordic Plastics: supplier sub-tier capacity constrained by 30%",    severity: "medium",   status: "resolved",     assignedTo: "Procurement",   category: "capacity",     supplier: "SUP-003", createdAt: "2026-03-01T12:00:00Z", region: "EU" },
  { id: "AL-1009", title: "Coastal Composites: insurance lapsed — shipment coverage gap",      severity: "low",      status: "open",         assignedTo: "Finance",       category: "financial",    supplier: "SUP-012", createdAt: "2026-02-28T10:10:00Z", region: "AMER" },
  { id: "AL-1010", title: "Pacific Circuits: Q4 delivery performance exceeded SLA target",     severity: "low",      status: "resolved",     assignedTo: "Supplier Mgmt", category: "performance",  supplier: "SUP-002", createdAt: "2026-02-25T08:00:00Z", region: "APAC" },
];

const shipments = [
  { id: "SHP-5001", supplier: "SUP-002", origin: "Taipei",      destination: "Rotterdam",  mode: "SEA",  status: "on-track", eta: "2026-03-14", daysDelayed: 0,  value: 420000, containers: 3 },
  { id: "SHP-5002", supplier: "SUP-001", origin: "Chennai",     destination: "Felixstowe", mode: "SEA",  status: "delayed",  eta: "2026-03-18", daysDelayed: 8,  value: 195000, containers: 2 },
  { id: "SHP-5003", supplier: "SUP-005", origin: "Busan",       destination: "Los Angeles",mode: "SEA",  status: "delayed",  eta: "2026-03-12", daysDelayed: 5,  value: 870000, containers: 6 },
  { id: "SHP-5004", supplier: "SUP-004", origin: "Hamburg",     destination: "Chicago",    mode: "AIR",  status: "on-track", eta: "2026-03-07", daysDelayed: 0,  value: 310000, containers: 1 },
  { id: "SHP-5005", supplier: "SUP-007", origin: "Shenzhen",    destination: "Dubai",      mode: "SEA",  status: "delayed",  eta: "2026-03-20", daysDelayed: 11, value: 145000, containers: 2 },
  { id: "SHP-5006", supplier: "SUP-010", origin: "Haifa",       destination: "Antwerp",    mode: "SEA",  status: "at-risk",  eta: "2026-03-16", daysDelayed: 3,  value: 280000, containers: 2 },
  { id: "SHP-5007", supplier: "SUP-012", origin: "Mexico City", destination: "Dallas",     mode: "RAIL", status: "on-track", eta: "2026-03-09", daysDelayed: 0,  value: 92000,  containers: 1 },
  { id: "SHP-5008", supplier: "SUP-003", origin: "Gothenburg",  destination: "Glasgow",    mode: "SEA",  status: "on-track", eta: "2026-03-10", daysDelayed: 0,  value: 165000, containers: 1 },
  { id: "SHP-5009", supplier: "SUP-006", origin: "Houston",     destination: "São Paulo",  mode: "AIR",  status: "at-risk",  eta: "2026-03-08", daysDelayed: 2,  value: 77000,  containers: 1 },
  { id: "SHP-5010", supplier: "SUP-011", origin: "Alexandria",  destination: "Barcelona",  mode: "SEA",  status: "delayed",  eta: "2026-03-22", daysDelayed: 7,  value: 112000, containers: 1 },
];

const riskEvents = [
  { date: "2026-03-06", type: "weather",      title: "Cyclone Nadia",                region: "APAC", impactedSuppliers: 3, severityScore: 91 },
  { date: "2026-03-05", type: "geopolitical", title: "Export control review (KR)",   region: "APAC", impactedSuppliers: 1, severityScore: 74 },
  { date: "2026-03-04", type: "transport",    title: "Hamburg port backlog +6d",     region: "EMEA", impactedSuppliers: 2, severityScore: 62 },
  { date: "2026-03-03", type: "transport",    title: "Haifa port strike",            region: "EMEA", impactedSuppliers: 1, severityScore: 58 },
  { date: "2026-03-02", type: "financial",    title: "Credit rating cut — SUP-001",  region: "EMEA", impactedSuppliers: 1, severityScore: 70 },
  { date: "2026-03-01", type: "esg",          title: "ESG audit violation",          region: "APAC", impactedSuppliers: 1, severityScore: 45 },
  { date: "2026-02-27", type: "weather",      title: "Snowstorm — Northeast USA",    region: "AMER", impactedSuppliers: 2, severityScore: 38 },
  { date: "2026-02-25", type: "capacity",     title: "Sub-tier capacity constraint", region: "EU",   impactedSuppliers: 1, severityScore: 41 },
];

// ─── Precomputed chart / metric documents ─────────────────────────────────────

const riskMetrics = [
  {
    type: "trend",
    description: "13-week platform-wide composite risk score",
    updatedAt: new Date().toISOString(),
    data: [
      { name: "W40", value: 41 }, { name: "W41", value: 39 }, { name: "W42", value: 44 },
      { name: "W43", value: 47 }, { name: "W44", value: 43 }, { name: "W45", value: 50 },
      { name: "W46", value: 55 }, { name: "W47", value: 52 }, { name: "W48", value: 61 },
      { name: "W49", value: 58 }, { name: "W50", value: 64 }, { name: "W51", value: 70 },
      { name: "W52", value: 67 },
    ],
  },
  {
    type: "byRegion",
    description: "Risk score per geographic region",
    updatedAt: new Date().toISOString(),
    data: [
      { name: "AMER", value: 38 },
      { name: "EU",   value: 44 },
      { name: "EMEA", value: 63 },
      { name: "APAC", value: 71 },
    ],
  },
  {
    type: "byDriver",
    description: "Risk contribution by category driver",
    updatedAt: new Date().toISOString(),
    data: [
      { name: "Weather",      value: 28 }, { name: "Financial",    value: 22 },
      { name: "Transport",    value: 19 }, { name: "Geopolitical", value: 14 },
      { name: "ESG",          value: 9  }, { name: "Capacity",     value: 8  },
    ],
  },
  {
    type: "shipmentDelays",
    description: "Delayed shipment count by transport mode",
    updatedAt: new Date().toISOString(),
    data: [
      { name: "SEA",  value: 18 }, { name: "AIR",  value: 5 },
      { name: "RAIL", value: 9  }, { name: "ROAD", value: 12 },
    ],
  },
  {
    type: "onTimeByWeek",
    description: "On-time vs delayed delivery ratio by week (last 8 weeks)",
    updatedAt: new Date().toISOString(),
    data: [
      { name: "W45", onTime: 84, delayed: 16 }, { name: "W46", onTime: 80, delayed: 20 },
      { name: "W47", onTime: 82, delayed: 18 }, { name: "W48", onTime: 77, delayed: 23 },
      { name: "W49", onTime: 79, delayed: 21 }, { name: "W50", onTime: 75, delayed: 25 },
      { name: "W51", onTime: 71, delayed: 29 }, { name: "W52", onTime: 73, delayed: 27 },
    ],
  },
];

// ─── Report definitions ───────────────────────────────────────────────────────

const reports = [
  { id: "RPT-001", title: "Weekly Supplier Risk Summary",     description: "Consolidated risk scores and alerts for all active suppliers, ranked by exposure.",       category: "risk",       lastRun: "2026-03-03T08:00:00Z", lastFormat: "PDF" },
  { id: "RPT-002", title: "Shipment Delay Analysis",          description: "Breakdown of delayed shipments by mode, region, and root cause for the past 4 weeks.",     category: "logistics",  lastRun: "2026-03-01T12:00:00Z", lastFormat: "CSV" },
  { id: "RPT-003", title: "ESG Compliance Audit Report",      description: "Supplier ESG scores, audit findings, and remediation status across all tier 1 & 2 vendors.",category: "compliance", lastRun: "2026-02-24T09:00:00Z", lastFormat: "PDF" },
  { id: "RPT-004", title: "Financial Exposure Dashboard",     description: "Spend concentration, credit risk flags, and open PO values per supplier and region.",       category: "finance",    lastRun: "2026-02-20T14:00:00Z", lastFormat: "XLSX" },
];

// ─── Seed ─────────────────────────────────────────────────────────────────────

async function seed() {
  const client = new MongoClient(MONGODB_URI);
  await client.connect();
  console.log("✅  Connected to MongoDB Atlas");

  const db = client.db(DB_NAME);

  const collections = {
    suppliers:    suppliers,
    alerts:       alerts,
    shipments:    shipments,
    risk_events:  riskEvents,
    risk_metrics: riskMetrics,
    reports:      reports,
  } as const;

  for (const [name, docs] of Object.entries(collections)) {
    const col = db.collection(name);
    // Drop existing data for a clean seed
    await col.deleteMany({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await col.insertMany(docs as any[]);
    console.log(`  ↳  ${name}: ${docs.length} documents inserted`);
  }

  // Create useful indexes
  await db.collection("suppliers").createIndex({ id: 1 }, { unique: true });
  await db.collection("suppliers").createIndex({ riskScore: -1 });
  await db.collection("suppliers").createIndex({ region: 1 });

  await db.collection("alerts").createIndex({ id: 1 }, { unique: true });
  await db.collection("alerts").createIndex({ severity: 1, status: 1 });
  await db.collection("alerts").createIndex({ supplier: 1 });

  await db.collection("shipments").createIndex({ id: 1 }, { unique: true });
  await db.collection("shipments").createIndex({ status: 1 });
  await db.collection("shipments").createIndex({ supplier: 1 });

  await db.collection("risk_events").createIndex({ date: -1 });
  await db.collection("risk_metrics").createIndex({ type: 1 }, { unique: true });
  await db.collection("reports").createIndex({ id: 1 }, { unique: true });

  console.log("\n✅  Indexes created");
  console.log("🎉  Seed complete — SCVRI database is ready!\n");

  await client.close();
}

seed().catch((err) => {
  console.error("❌  Seed failed:", err);
  process.exit(1);
});
