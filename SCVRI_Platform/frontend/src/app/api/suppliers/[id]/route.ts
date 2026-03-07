import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const db = await getDb();
    const supplier = await db.collection("suppliers").findOne({ id });
    if (!supplier) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const { _id, ...data } = supplier;
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/suppliers/[id] GET error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const body = await req.json();
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { _id: _d1, id: _d2, ...updates } = body;
    const db = await getDb();
    const result = await db
      .collection("suppliers")
      .findOneAndUpdate({ id }, { $set: updates }, { returnDocument: "after" });
    if (!result) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const { _id, ...data } = result;
    return NextResponse.json(data);
  } catch (err) {
    console.error("/api/suppliers/[id] PATCH error:", err);
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
    const result = await db.collection("suppliers").deleteOne({ id });
    if (result.deletedCount === 0) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json({ id, deleted: true });
  } catch (err) {
    console.error("/api/suppliers/[id] DELETE error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
