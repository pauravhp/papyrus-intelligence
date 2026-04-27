import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * Returns true if the signed-in user still needs to finish onboarding —
 * i.e. either Google Calendar or Todoist isn't connected yet.
 *
 * Connection state lives in two columns on `users`:
 *   - google_credentials   (jsonb, populated by /auth/google OAuth)
 *   - todoist_oauth_token  (jsonb { access_token, ... }, populated by /auth/todoist)
 *
 * On any query failure, returns `false` (fail-open) so a transient DB blip
 * never traps a real user in a redirect loop.
 */
export async function needsOnboarding(supabase: SupabaseClient): Promise<boolean> {
  try {
    const { data, error } = await supabase
      .from("users")
      .select("google_credentials, todoist_oauth_token")
      .maybeSingle();
    if (error || !data) return false;
    const hasGcal = !!data.google_credentials;
    const hasTodoist = !!(
      data.todoist_oauth_token as { access_token?: string } | null
    )?.access_token;
    return !(hasGcal && hasTodoist);
  } catch {
    return false;
  }
}
