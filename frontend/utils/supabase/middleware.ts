import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!;

/**
 * Creates a Supabase client scoped to the current request/response cycle.
 * Returns both the client and the response so the caller can:
 *   1. Call supabase.auth.getClaims() for JWT-validated auth checks.
 *   2. Return supabaseResponse to forward refreshed session cookies to the browser.
 *
 * NOTE: The Supabase-provided template only returns supabaseResponse. We also
 * return supabase here so middleware.ts can call getClaims() without creating
 * a second client (which would have a separate cookie setAll closure).
 */
export const createClient = (request: NextRequest) => {
  let supabaseResponse = NextResponse.next({
    request: { headers: request.headers },
  });

  const supabase = createServerClient(supabaseUrl, supabaseKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value),
        );
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options),
        );
      },
    },
  });

  return { supabase, supabaseResponse };
};
