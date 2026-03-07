import { NextResponse } from "next/server";

export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set("scvri_session", "", { maxAge: 0, path: "/" });
  res.cookies.set("scvri_refresh", "", { maxAge: 0, path: "/" });
  return res;
}
