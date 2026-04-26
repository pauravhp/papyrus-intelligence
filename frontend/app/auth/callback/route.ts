import { type NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

/**
 * Handles the auth callback after email confirmation or OAuth redirect.
 * Exchanges the ?code= param for a session, then:
 *   - if user email is in BETA_ALLOWLIST (backend-checked) → redirect to /today (or ?next=)
 *   - otherwise → auto-add to Resend waitlist + signOut + redirect to /waitlist-pending
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/today";

  if (!code) {
    return NextResponse.redirect(
      new URL("/login?error=auth-callback-failed", request.url),
    );
  }

  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);

  const { data: sessionData, error: exchangeError } =
    await supabase.auth.exchangeCodeForSession(code);
  if (exchangeError || !sessionData.session) {
    return NextResponse.redirect(
      new URL("/login?error=auth-callback-failed", request.url),
    );
  }

  // Beta gate
  const token = sessionData.session.access_token;
  let allowed = false;
  let email = sessionData.user?.email ?? "";
  try {
    const accessRes = await fetch(`${API_BASE}/api/me/access`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (accessRes.ok) {
      const json = (await accessRes.json()) as { allowed: boolean; email?: string };
      allowed = json.allowed;
      if (json.email) email = json.email;
    }
  } catch {
    // Network error → fail closed (treat as rejected). Better to bounce a real
    // beta user (they can retry) than to admit a stranger.
    allowed = false;
  }

  if (allowed) {
    return NextResponse.redirect(new URL(next, request.url));
  }

  // Rejected → auto-add to Resend (best-effort, ignore failure) + signOut + redirect.
  // Pull first name from Google OAuth metadata since the user never saw a form.
  if (email) {
    const meta = sessionData.user?.user_metadata as
      | { given_name?: string; full_name?: string; name?: string }
      | undefined;
    const firstName =
      meta?.given_name ??
      meta?.full_name?.trim().split(/\s+/)[0] ??
      meta?.name?.trim().split(/\s+/)[0];

    try {
      await fetch(new URL("/api/waitlist", request.url), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, firstName }),
      });
    } catch {
      // ignore — waitlist add is best-effort
    }
  }
  await supabase.auth.signOut();

  const dest = new URL("/waitlist-pending", request.url);
  if (email) dest.searchParams.set("email", email);
  return NextResponse.redirect(dest);
}
