import { type NextRequest, NextResponse } from "next/server";
import { createClient } from "@/utils/supabase/middleware";

export async function proxy(request: NextRequest) {
  const { supabase, supabaseResponse } = createClient(request);

  // getClaims() validates the JWT locally against the project's cached JWKS
  // (asymmetric key) — or falls back to getUser() for symmetric keys.
  // Never use getSession() in server/middleware code: it reads the cookie without
  // cryptographic validation and can be spoofed.
  const { data } = await supabase.auth.getClaims();
  const isAuthenticated = !!data?.claims;

  const { pathname } = request.nextUrl;

  if (!isAuthenticated && pathname.startsWith("/dashboard")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (isAuthenticated && pathname === "/login") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Always return supabaseResponse so refreshed session cookies are forwarded.
  return supabaseResponse;
}

export const config = {
  matcher: [
    // Skip Next.js internals and static files; run on everything else.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
