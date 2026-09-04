import { NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";
import { riskMetrics } from "@/services/mockData";

export async function GET() {
  try {
    const db = await getDb();
    const doc = await db.collection("risk_metrics").findOne({ type: "shipmentDelays" });
    if (doc?.data) return NextResponse.json(doc.data);
  } catch (err) {
    // Database offline — fall back to mock data
  }
  return NextResponse.json(riskMetrics.shipmentDelays);
}
