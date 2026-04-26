// frontend/app/dashboard/settings/page.tsx
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import Sidebar from "@/components/Sidebar";
import SettingsClient from "./SettingsClient";

export default async function SettingsPage() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data, error } = await supabase.auth.getClaims();

  if (!data?.claims || error) {
    redirect("/login");
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)", color: "var(--text)" }}>
      <Sidebar />
      <main style={{ flex: 1, marginLeft: 56, padding: "40px 48px 80px" }}>
        <div style={{ maxWidth: 620 }}>
          <h1
            className="font-display"
            style={{ fontSize: 32, fontWeight: 400, color: "var(--text)", letterSpacing: "-0.01em", lineHeight: 1.1 }}
          >
            Settings
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", fontStyle: "italic", marginTop: 4 }}>
            Your tools, your schedule, your way.
          </p>
          <SettingsClient />
        </div>
      </main>
    </div>
  );
}
