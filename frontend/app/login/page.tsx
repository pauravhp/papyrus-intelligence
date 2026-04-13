// frontend/app/login/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/utils/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const supabase = createClient();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setLoading(true);

    if (mode === "signin") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setError(error.message);
      } else {
        router.push("/dashboard");
        router.refresh();
      }
    } else {
      const { error } = await supabase.auth.signUp({ email, password });
      if (error) {
        setError(error.message);
      } else {
        setMessage("Check your email to confirm your account, then sign in.");
      }
    }

    setLoading(false);
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    background: "var(--surface-raised)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    padding: "8px 12px",
    fontSize: 13,
    color: "var(--text)",
    outline: "none",
    fontFamily: "var(--font-literata)",
  };

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: 11,
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    color: "var(--text-muted)",
    marginBottom: 6,
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
            marginBottom: 28,
            fontWeight: 400,
            letterSpacing: "-0.01em",
          }}
        >
          {mode === "signin" ? "Sign in" : "Create account"}
        </h1>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={labelStyle}>Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
            />
          </div>

          {error && (
            <p style={{ fontSize: 13, color: "var(--danger)" }}>{error}</p>
          )}
          {message && (
            <p style={{ fontSize: 13, color: "var(--accent)" }}>{message}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "10px 0",
              borderRadius: 8,
              background: "var(--accent)",
              color: "var(--bg)",
              border: "none",
              fontSize: 14,
              fontFamily: "var(--font-literata)",
              cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.6 : 1,
              transition: "opacity 0.15s",
            }}
          >
            {loading ? "Loading" : mode === "signin" ? "Sign in" : "Sign up"}
          </button>
        </form>

        <p
          style={{
            fontSize: 13,
            textAlign: "center",
            color: "var(--text-muted)",
            marginTop: 20,
          }}
        >
          {mode === "signin" ? "No account?" : "Already have one?"}{" "}
          <button
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setMessage(null);
            }}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--accent)",
              fontSize: 13,
              textDecoration: "underline",
              textUnderlineOffset: 3,
              fontFamily: "var(--font-literata)",
            }}
          >
            {mode === "signin" ? "Sign up" : "Sign in"}
          </button>
        </p>
      </div>
    </div>
  );
}
