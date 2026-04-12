import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import ConnectGoogleButton from "./ConnectGoogleButton";
import SignOutButton from "./SignOutButton";

export default async function DashboardPage() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data, error } = await supabase.auth.getClaims();

  if (!data?.claims || error) {
    redirect("/login");
  }

  // If user hasn't completed onboarding, send them there
  const userId = data.claims.sub as string;
  const { data: userRow } = await supabase
    .from("users")
    .select("config")
    .eq("id", userId)
    .maybeSingle();

  const isOnboarded =
    userRow?.config && Object.keys(userRow.config).length > 0;
  if (!isOnboarded) {
    redirect("/onboard?stage=0");
  }

  const email = data.claims.email as string;

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm bg-white rounded-xl shadow p-8 space-y-4">
        <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-600">
          Logged in as{" "}
          <span className="font-medium text-gray-900">{email}</span>
        </p>
        <ConnectGoogleButton />
        <SignOutButton />
      </div>
    </div>
  );
}
