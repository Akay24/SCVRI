import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function PATCH(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const db = await getDb();
    const result = await db
      .collection("alerts")
      .findOneAndUpdate(
        { id },
        { $set: { status: "acknowledged" } },
        { returnDocument: "after" }
      );
    if (!result) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const { _id, ...data } = result;
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/alerts/[id]/acknowledge error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
