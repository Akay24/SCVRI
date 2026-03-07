import { NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function GET() {
  try {
    const db = await getDb();
    const events = await db
      .collection("risk_events")
      .find({})
      .sort({ date: -1 })
      .toArray();
    const data = events.map(({ _id, ...rest }) => rest);
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/risk/events error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
