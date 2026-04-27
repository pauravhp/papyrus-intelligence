// frontend/app/login/page.tsx
"use client";

import { useState } from "react";
import { createClient } from "@/utils/supabase/client";

export default function LoginPage() {
  const supabase = createClient();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGoogleSignIn = async () => {
    setError(null);
    setLoading(true);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (error) {
      setError(error.message);
      setLoading(false);
    }
    // On success, browser navigates away — no need to setLoading(false)
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
        padding: "0 16px",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 360,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 16,
          padding: "36px 32px",
        }}
      >
        <h1
          className="font-display"
          style={{
            fontSize: 26,
            color: "var(--text)",
            marginBottom: 8,
            fontWeight: 400,
            letterSpacing: "-0.01em",
          }}
        >
          Papyrus
        </h1>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-muted)",
            marginBottom: 28,
            fontFamily: "var(--font-literata)",
          }}
        >
          Your scheduling coach
        </p>

        {error && (
          <p role="alert" style={{ fontSize: 13, color: "var(--danger)", marginBottom: 16 }}>
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={loading}
          style={{
            width: "100%",
            padding: "13px 0",
            minHeight: 46,
            borderRadius: 8,
            background: "var(--accent)",
            color: "var(--bg)",
            border: "none",
            fontSize: 15,
            fontFamily: "var(--font-literata)",
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading ? 0.6 : 1,
            transition: "opacity 0.15s",
          }}
        >
          {loading ? "Redirecting…" : "Sign in with Google"}
        </button>
      </div>
    </div>
  );
}
