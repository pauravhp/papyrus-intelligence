import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import { needsOnboarding } from "@/utils/onboarding";
import Sidebar from "@/components/Sidebar";
import TodayPage from "./TodayPage";

export default async function TodayRoute() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data, error } = await supabase.auth.getClaims();

  if (!data?.claims || error) {
    redirect("/login");
  }

  // Belt-and-suspenders for the auth-callback guard: if a logged-in user
  // navigates here directly without finishing /onboard, send them back.
  if (await needsOnboarding(supabase)) {
    redirect("/onboard");
  }

  return (
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        background: "var(--bg)",
        color: "var(--text)",
      }}
    >
      <Sidebar />
      <main style={{ flex: 1, marginLeft: 56 }}>
        <TodayPage />
      </main>
    </div>
  );
}
