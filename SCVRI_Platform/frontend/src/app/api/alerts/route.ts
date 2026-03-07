import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const severity = searchParams.get("severity");
  const status   = searchParams.get("status");
  const region   = searchParams.get("region");

  const filter: Record<string, string> = {};
  if (severity) filter["severity"] = severity;
  if (status)   filter["status"]   = status;
  if (region)   filter["region"]   = region;

  try {
    const db = await getDb();
    const alerts = await db
      .collection("alerts")
      .find(filter)
      .sort({ createdAt: -1 })
      .toArray();
    const data = alerts.map(({ _id, ...rest }) => rest);
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/alerts error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.title || !body.severity) {
      return NextResponse.json({ error: "title and severity are required" }, { status: 400 });
    }
    const db = await getDb();
    const count = await db.collection("alerts").countDocuments();
    const id = `AL-${String(1001 + count).padStart(4, "0")}`;
    const doc = {
      id,
      title: body.title,
      severity: body.severity,
      status: "open" as const,
      assignedTo: body.assignedTo || "Unassigned",
      category: body.category || "other",
      supplier: body.supplier || "",
      createdAt: new Date().toISOString(),
      region: body.region || "AMER",
    };
    await db.collection("alerts").insertOne(doc);
    return NextResponse.json(doc, { status: 201 });
  } catch (err) {
    console.error("/api/alerts POST error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
