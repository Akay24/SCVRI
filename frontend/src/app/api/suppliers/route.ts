import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/mongodb";
import { suppliers as mockSuppliers } from "@/services/mockData";

export async function GET() {
  try {
    const db = await getDb();
    const suppliers = await db.collection("suppliers").find({}).sort({ riskScore: -1 }).toArray();
    if (suppliers && suppliers.length > 0) {
      const data = suppliers.map(({ _id, ...rest }) => rest);
      return NextResponse.json(data);
    }
  } catch (err) {
    // Database offline — fall back to mock data
  }
  return NextResponse.json(mockSuppliers);
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.name || !body.country) {
      return NextResponse.json({ error: "name and country are required" }, { status: 400 });
    }
    const db = await getDb();
    const count = await db.collection("suppliers").countDocuments();
    const id = `SUP-${String(count + 1).padStart(3, "0")}`;
    const doc = {
      id,
      name: body.name,
      riskScore: Number(body.riskScore) || 0,
      spend: Number(body.spend) || 0,
      activePOs: Number(body.activePOs) || 0,
      region: body.region || "AMER",
      tier: Number(body.tier) || 3,
      category: body.category || "Other",
      onTimeDelivery: Number(body.onTimeDelivery) || 100,
      qualityYield: Number(body.qualityYield) || 100,
      inTransit: Number(body.inTransit) || 0,
      delayed: Number(body.delayed) || 0,
      country: body.country,
    };
    await db.collection("suppliers").insertOne(doc);
    return NextResponse.json(doc, { status: 201 });
  } catch (err) {
    console.error("/api/suppliers POST error:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
