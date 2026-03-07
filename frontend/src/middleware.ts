import { NextRequest, NextResponse } from "next/server";

/** Paths that never require authentication. */
const PUBLIC_PREFIXES = ["/login", "/api/auth/"];

/** Static asset patterns that should always pass through. */
const ASSET_REGEX = /^\/_next\/|^\/favicon\.ico$/;

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (ASSET_REGEX.test(pathname)) return NextResponse.next();
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) return NextResponse.next();

  // All other routes require a session cookie
  const session = req.cookies.get("scvri_session");
  if (!session?.value) {
    const loginUrl = new URL("/login", req.url);
    if (pathname !== "/") loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
