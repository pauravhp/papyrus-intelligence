import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import Sidebar from "@/components/Sidebar";
import ChatWindow from "@/app/_archive/ChatWindow";

export default async function ChatRoute() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data, error } = await supabase.auth.getClaims();

  if (!data?.claims || error) {
    redirect("/login");
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
