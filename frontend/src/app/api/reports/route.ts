import { NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";
import { reports as mockReports } from "@/services/mockData";

export async function GET() {
  try {
    const db = await getDb();
    const reports = await db.collection("reports").find({}).sort({ lastRun: -1 }).toArray();
    if (reports && reports.length > 0) {
      const data = reports.map(({ _id, ...rest }) => rest);
      return NextResponse.json(data);
    }
  } catch (err) {
    // Database offline — fall back to mock data
  }
  return NextResponse.json(mockReports);
}
