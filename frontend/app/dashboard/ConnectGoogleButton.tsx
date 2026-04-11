"use client";

import { createClient } from "@/utils/supabase/client";

const BACKEND_GOOGLE_AUTH = "http://localhost:8000/auth/google";

export default function ConnectGoogleButton() {
  const supabase = createClient();

  const handleConnect = async () => {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return;
    window.location.href = `${BACKEND_GOOGLE_AUTH}?token=${token}`;
  };

  return (
    <button
      onClick={handleConnect}
      className="w-full border border-gray-300 rounded-lg py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
    >
      Connect Google Calendar
    </button>
  );
}
