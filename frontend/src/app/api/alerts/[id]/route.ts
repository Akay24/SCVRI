import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const body = await req.json();
    const { _id: _drop, id: _dropId, ...updates } = body;
    const db = await getDb();
    const result = await db
      .collection("alerts")
      .findOneAndUpdate({ id }, { $set: updates }, { returnDocument: "after" });
    if (!result) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const { _id, ...data } = result;
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/alerts/[id] PATCH error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const db = await getDb();
    const result = await db.collection("alerts").deleteOne({ id });
    if (result.deletedCount === 0) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json({ id, deleted: true });
  } catch (err) {
    console.error("/api/alerts/[id] DELETE error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
