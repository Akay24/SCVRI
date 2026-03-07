import { NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function GET() {
  try {
    const db = await getDb();
    const doc = await db.collection("risk_metrics").findOne({ type: "byDriver" });
    if (!doc) return NextResponse.json({ error: "No data" }, { status: 404 });
    return NextResponse.json(doc.data);
  } catch (err) {
    console.error("/api/risk/by-driver error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
