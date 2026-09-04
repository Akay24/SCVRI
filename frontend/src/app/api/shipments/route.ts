import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";
import { shipments as mockShipments } from "@/services/mockData";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status   = searchParams.get("status");
  const supplier = searchParams.get("supplier");

  const filter: Record<string, string> = {};
  if (status)   filter["status"]   = status;
  if (supplier) filter["supplier"] = supplier;

  try {
    const db = await getDb();
    const shipments = await db
      .collection("shipments")
      .find(filter)
      .sort({ eta: 1 })
      .toArray();
    if (shipments && shipments.length > 0) {
      const data = shipments.map(({ _id, ...rest }) => rest);
      return NextResponse.json(data);
    }
  } catch (err) {
    // Database offline — fall back to mock data
  }

  let result = [...mockShipments];
  if (status)   result = result.filter((s) => s.status === status);
  if (supplier) result = result.filter((s) => s.supplier === supplier);
  return NextResponse.json(result);
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.supplier || !body.origin || !body.destination) {
      return NextResponse.json({ error: "supplier, origin and destination are required" }, { status: 400 });
    }
    const db = await getDb();
    const count = await db.collection("shipments").countDocuments();
    const id = `SHP-${String(5001 + count).padStart(4, "0")}`;
    const doc = {
      id,
      supplier: body.supplier,
      origin: body.origin,
      destination: body.destination,
      mode: body.mode || "SEA",
      status: body.status || "on-track",
      eta: body.eta || new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10),
      daysDelayed: Number(body.daysDelayed) || 0,
      value: Number(body.value) || 0,
      containers: Number(body.containers) || 1,
    };
    await db.collection("shipments").insertOne(doc);
    return NextResponse.json(doc, { status: 201 });
  } catch (err) {
    console.error("/api/shipments POST error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
