"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, CalendarDays, Key } from "lucide-react";
import { createClient } from "@/utils/supabase/client";
import { apiPost } from "@/utils/api";

const CARD: React.CSSProperties = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  backdropFilter: "blur(12px)",
  borderRadius: 16,
  padding: "20px",
};

const INPUT: React.CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  border: "1px solid rgba(255,255,255,0.1)",
  color: "#f8fafc",
  width: "100%",
  fontSize: 13,
  padding: "8px 12px",
  borderRadius: 8,
  outline: "none",
};

interface SetupStageProps {
  onAdvance: (timezone: string, calendarIds: string[]) => void;
}

export default function SetupStage({ onAdvance }: SetupStageProps) {
  const supabase = createClient();
  const [gcalConnected, setGcalConnected] = useState(false);
  const [checking, setChecking] = useState(true);
  const [todoistKey, setTodoistKey] = useState("");
  const [llmKey, setLlmKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    supabase
      .from("users")
      .select("google_credentials")
      .maybeSingle()
      .then(({ data }) => {
        setGcalConnected(!!data?.google_credentials);
        setChecking(false);
      });
  }, []);

  const handleConnectGoogle = async () => {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return;
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/auth/google?token=${token}`;
  };

  const canContinue = gcalConnected && todoistKey.trim() && llmKey.trim();

  const handleContinue = async () => {
    if (!canContinue) return;
    setLoading(true);
    setError(null);

    const isGroq = llmKey.trim().startsWith("gsk_");
    const isAnthropic = llmKey.trim().startsWith("sk-ant-");
    if (!isGroq && !isAnthropic) {
      setError("LLM key must start with gsk_ (Groq) or sk-ant- (Anthropic).");
      setLoading(false);
      return;
    }

    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";

      await apiPost(
        "/api/onboard/save-credentials",
        {
          groq_api_key: isGroq ? llmKey.trim() : "",
          anthropic_api_key: isAnthropic ? llmKey.trim() : "",
          todoist_api_key: todoistKey.trim(),
        },
        token,
      );

      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      onAdvance(timezone, []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const FADE = {
    hidden: { opacity: 0, y: 16 },
    show: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        delay: i * 0.08,
        type: "spring" as const,
        stiffness: 100,
        damping: 14,
      },
    }),
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{ background: "#080810" }}
    >
      <motion.div
        initial="hidden"
        animate="show"
        className="w-full max-w-sm sm:max-w-md space-y-4"
      >
        <motion.div custom={0} variants={FADE} className="text-center mb-4">
          <h1
            className="font-display text-white"
            style={{
              fontSize: "clamp(1.8rem, 4vw, 2.4rem)",
              letterSpacing: "-0.025em",
            }}
          >
            Connect your tools
          </h1>
          <p style={{ color: "#94a3b8", fontSize: 13, marginTop: 6 }}>
            Papyrus needs access to your calendar, tasks, and an AI model.
          </p>
        </motion.div>

        {/* Google Calendar */}
        <motion.div custom={1} variants={FADE} style={CARD}>
          <div className="flex items-start gap-3">
            <div
              style={{
                background: "rgba(99,102,241,0.15)",
                padding: 8,
                borderRadius: 8,
              }}
            >
              <CalendarDays size={18} color="#6366f1" />
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ color: "#f8fafc", fontSize: 13, fontWeight: 500 }}>
                Google Calendar
              </p>
              <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 2 }}>
                Required — Papyrus reads and writes your events.
              </p>
              <div style={{ marginTop: 10 }}>
                {checking ? (
                  <p style={{ color: "#475569", fontSize: 12 }}>Checking…</p>
                ) : gcalConnected ? (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      color: "#34d399",
                      fontSize: 12,
                    }}
                  >
                    <CheckCircle2 size={13} /> Connected
                  </div>
                ) : (
                  <motion.button
                    onClick={handleConnectGoogle}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    style={{
                      background: "#6366f1",
                      color: "#fff",
                      border: "none",
                      borderRadius: 8,
                      padding: "6px 14px",
                      fontSize: 12,
                      fontWeight: 500,
                      cursor: "pointer",
                    }}
                  >
                    Connect Google Calendar
                  </motion.button>
                )}
              </div>
            </div>
          </div>
        </motion.div>

        {/* API Keys */}
        <motion.div
          custom={2}
          variants={FADE}
          style={{ ...CARD, display: "flex", flexDirection: "column", gap: 14 }}
        >
          <div className="flex items-center gap-3">
            <div
              style={{
                background: "rgba(99,102,241,0.15)",
                padding: 8,
                borderRadius: 8,
              }}
            >
              <Key size={18} color="#6366f1" />
            </div>
            <div>
              <p style={{ color: "#f8fafc", fontSize: 13, fontWeight: 500 }}>
                API Keys
              </p>
              <p style={{ color: "#94a3b8", fontSize: 12 }}>
                Stored encrypted — never logged.
              </p>
            </div>
          </div>

          <div>
            <label
              style={{
                color: "#94a3b8",
                fontSize: 11,
                fontWeight: 500,
                display: "block",
                marginBottom: 4,
              }}
            >
              Todoist API key{" "}
              <span style={{ color: "#f43f5e" }}>*</span>
            </label>
            <input
              type="password"
              value={todoistKey}
              onChange={(e) => {
                setTodoistKey(e.target.value);
                setError(null);
              }}
              placeholder="Your Todoist token"
              style={INPUT}
            />
          </div>

          <div>
            <label
              style={{
                color: "#94a3b8",
                fontSize: 11,
                fontWeight: 500,
                display: "block",
                marginBottom: 4,
              }}
            >
              LLM API key <span style={{ color: "#f43f5e" }}>*</span>
              <span
                style={{
                  color: "#475569",
                  fontWeight: 400,
                  marginLeft: 6,
                }}
              >
                gsk_… (Groq) or sk-ant-… (Anthropic)
              </span>
            </label>
            <input
              type="password"
              value={llmKey}
              onChange={(e) => {
                setLlmKey(e.target.value);
                setError(null);
              }}
              placeholder="gsk_… or sk-ant-…"
              style={INPUT}
            />
          </div>
        </motion.div>

        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{ color: "#f43f5e", fontSize: 12, textAlign: "center" }}
          >
            {error}
          </motion.p>
        )}

        <motion.div custom={3} variants={FADE}>
          <motion.button
            onClick={handleContinue}
            disabled={!canContinue || loading}
            whileHover={canContinue && !loading ? { scale: 1.01 } : undefined}
            whileTap={canContinue && !loading ? { scale: 0.99 } : undefined}
            style={{
              width: "100%",
              padding: "12px 0",
              borderRadius: 12,
              background:
                canContinue && !loading
                  ? "#6366f1"
                  : "rgba(99,102,241,0.3)",
              color: "#fff",
              border: "none",
              fontSize: 14,
              fontWeight: 500,
              cursor: canContinue && !loading ? "pointer" : "not-allowed",
              boxShadow:
                canContinue && !loading
                  ? "0 0 20px rgba(99,102,241,0.35)"
                  : "none",
            }}
          >
            {loading ? "Saving…" : "Continue →"}
          </motion.button>
        </motion.div>
      </motion.div>
    </div>
  );
}
