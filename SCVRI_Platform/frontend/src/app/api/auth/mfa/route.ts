import { NextRequest, NextResponse } from "next/server";

const IAM_URL = process.env.IAM_URL ?? "http://localhost:8000";

function mapRole(iamRole: string): "admin" | "analyst" | "viewer" {
  if (iamRole === "it_administrator") return "admin";
  if (["supply_chain_manager", "procurement_officer", "risk_analyst"].includes(iamRole)) return "analyst";
  return "viewer";
}

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  let iamRes: Response;
  try {
    iamRes = await fetch(`${IAM_URL}/auth/mfa/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return NextResponse.json({ error: "Auth service unreachable" }, { status: 503 });
  }

  const data = await iamRes.json();

  if (!iamRes.ok) {
    return NextResponse.json(data, { status: iamRes.status });
  }

  const role = mapRole(data.role);
  const res = NextResponse.json({ userId: data.userId, tenantId: data.tenantId, role });

  res.cookies.set("scvri_session", data.accessToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: data.expiresIn ?? 3600,
    path: "/",
  });

  res.cookies.set("scvri_refresh", data.refreshToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 30 * 24 * 60 * 60,
    path: "/",
  });

  return res;
}
