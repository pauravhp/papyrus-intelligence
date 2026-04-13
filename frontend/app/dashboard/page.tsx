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
  const { data: userRow } = await supabase
    .from("users")
    .select("config")
    .eq("id", userId)
    .maybeSingle();

  const isOnboarded = userRow?.config && Object.keys(userRow.config).length > 0;
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
