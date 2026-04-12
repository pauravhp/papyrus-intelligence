import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { Suspense } from "react";
import { createClient } from "@/utils/supabase/server";
import OnboardClient from "./OnboardClient";

export default async function OnboardPage() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data, error } = await supabase.auth.getClaims();

  if (!data?.claims || error) {
    redirect("/login");
  }

  // Already onboarded → skip back to dashboard
  const userId = data.claims.sub as string;
  const { data: userRow } = await supabase
    .from("users")
    .select("config")
    .eq("id", userId)
    .maybeSingle();

  const isOnboarded =
    userRow?.config && Object.keys(userRow.config).length > 0;
  if (isOnboarded) {
    redirect("/dashboard");
  }

  return (
    <Suspense
      fallback={
        <div
          className="min-h-screen flex items-center justify-center"
          style={{ background: "#080810" }}
        />
      }
    >
      <OnboardClient />
    </Suspense>
  );
}
