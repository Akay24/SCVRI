import { NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function GET() {
  try {
    const db = await getDb();
    const reports = await db.collection("reports").find({}).sort({ lastRun: -1 }).toArray();
    const data = reports.map(({ _id, ...rest }) => rest);
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/reports error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
