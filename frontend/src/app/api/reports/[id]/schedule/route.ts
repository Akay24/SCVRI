import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const format: string = body.format ?? "PDF";

  try {
    const db = await getDb();
    const result = await db
      .collection("reports")
      .findOneAndUpdate(
        { id },
        { $set: { lastRun: new Date().toISOString(), lastFormat: format } },
        { returnDocument: "after" }
      );
    if (!result) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json({ reportId: id, status: "scheduled", format });
  } catch (err) {
    console.error("/api/reports/[id]/schedule error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
