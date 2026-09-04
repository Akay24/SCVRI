import { NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";
import { riskEvents } from "@/services/mockData";

export async function GET() {
  try {
    const db = await getDb();
    const events = await db
      .collection("risk_events")
      .find({})
      .sort({ date: -1 })
      .toArray();
    if (events && events.length > 0) {
      const data = events.map(({ _id, ...rest }) => rest);
      return NextResponse.json(data);
    }
  } catch (err) {
    // Database offline — fall back to mock data
  }
  return NextResponse.json(riskEvents);
}
