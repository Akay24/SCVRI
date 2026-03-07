import { NextRequest, NextResponse } from "next/server";

const IAM_URL = process.env.IAM_URL ?? "http://localhost:8000";

/** Map IAM platform roles → frontend nav roles */
function mapRole(iamRole: string): "admin" | "analyst" | "viewer" {
  if (iamRole === "it_administrator") return "admin";
  if (["supply_chain_manager", "procurement_officer", "risk_analyst"].includes(iamRole)) return "analyst";
  return "viewer";
}

// ---------------------------------------------------------------------------
// DEV BYPASS — set DEV_AUTH_BYPASS=true in .env.local to skip the IAM service
// ---------------------------------------------------------------------------
const DEV_USERS: Record<string, { password: string; iamRole: string; name: string }> = {
  "admin@scvri.dev":       { password: "Admin1234!",   iamRole: "it_administrator",      name: "Alex Admin" },
  "manager@scvri.dev":     { password: "Manager1!",    iamRole: "supply_chain_manager",  name: "Sam Manager" },
  "procurement@scvri.dev": { password: "Procure1!",    iamRole: "procurement_officer",   name: "Pat Procurement" },
  "analyst@scvri.dev":     { password: "Analyst1!",    iamRole: "risk_analyst",          name: "Riley Analyst" },
  "viewer@scvri.dev":      { password: "Viewer12!",    iamRole: "viewer",                name: "Val Viewer" },
};

function devBypass(req: NextRequest, body: Record<string, string>): NextResponse | null {
  if (process.env.DEV_AUTH_BYPASS !== "true") return null;
  const user = DEV_USERS[body.email?.toLowerCase()];
  if (!user || user.password !== body.password) {
    return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
  }
  const role = mapRole(user.iamRole);
  const fakeUserId = Buffer.from(body.email).toString("base64").slice(0, 22);
  const res = NextResponse.json({ userId: fakeUserId, tenantId: "dev-tenant", role });
  const maxAge = 3600;
  const cookieOpts = {
    httpOnly: true,
    secure: false,
    sameSite: "lax" as const,
    path: "/",
  };
  res.cookies.set("scvri_session", `dev.${fakeUserId}`, { ...cookieOpts, maxAge });
  res.cookies.set("scvri_refresh", `dev.refresh.${fakeUserId}`, { ...cookieOpts, maxAge: 30 * 86400 });
  return res;
}

export async function POST(req: NextRequest) {
  let body: Record<string, string>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  // Dev bypass short-circuit
  const devRes = devBypass(req, body);
  if (devRes) return devRes;

  let iamRes: Response;
  try {
    iamRes = await fetch(`${IAM_URL}/auth/login`, {
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

  // MFA step 1 — no cookie yet, client must complete MFA
  if (data.mfaRequired) {
    return NextResponse.json(data);
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

