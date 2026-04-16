import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import ChatWindow from "./ChatWindow";
import Sidebar from "@/components/Sidebar";

export default async function DashboardPage() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data, error } = await supabase.auth.getClaims();

  if (!data?.claims || error) {
    redirect("/login");
  }

  const userId = data.claims.sub as string;
  const { data: userRow, error: dbError } = await supabase
    .from("users")
    .select("config, google_credentials, todoist_oauth_token")
    .eq("id", userId)
    .maybeSingle();

  if (dbError) {
    console.error("[DashboardPage] failed to load user row:", dbError.message);
    redirect("/login");
  }

  const hasGcal    = !!userRow?.google_credentials;
  const hasTodoist = !!userRow?.todoist_oauth_token;
  const isOnboarded =
    hasGcal &&
    hasTodoist &&
    Object.keys(userRow?.config ?? {}).length > 0;
  if (!isOnboarded) {
    redirect("/onboard");
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)", color: "var(--text)" }}>
      <Sidebar />
      <main style={{ flex: 1, marginLeft: 56 }}>
        <ChatWindow />
      </main>
    </div>
  );
}
