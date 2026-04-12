import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import ChatWindow from "./ChatWindow";
import SignOutButton from "./SignOutButton";

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
    redirect("/onboard?stage=0");
  }

  return (
    <div style={{ background: "#080810", minHeight: "100vh", color: "#f8fafc" }}>
      <div
        style={{
          position: "fixed",
          top: 16,
          right: 16,
          zIndex: 50,
        }}
      >
        <SignOutButton />
      </div>
      <ChatWindow />
    </div>
  );
}
