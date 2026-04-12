"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, CalendarDays, Key } from "lucide-react";
import { createClient } from "@/utils/supabase/client";
import StepDots from "@/components/StepDots";

// ── Animation variants (inspired by 21st.dev stagger pattern) ────────────

const CONTAINER = {
  hidden: {},
  show: { transition: { staggerChildren: 0.09 } },
};
const ITEM = {
  hidden: { opacity: 0, y: 18 },
  show: {
    opacity: 1,
    y: 0,
    transition: { type: "spring" as const, stiffness: 100, damping: 14 },
  },
};

type GoogleStatus = "loading" | "connected" | "disconnected";

interface Stage0Props {
  onAdvance: () => void;
}

// ── Shared card style ─────────────────────────────────────────────────────

const CARD_STYLE: React.CSSProperties = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  backdropFilter: "blur(12px)",
};

const INPUT_STYLE: React.CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  border: "1px solid rgba(255,255,255,0.1)",
  color: "#f8fafc",
};

export default function Stage0({ onAdvance }: Stage0Props) {
  const supabase = createClient();
  const [googleStatus, setGoogleStatus] = useState<GoogleStatus>("loading");
  const [groqKey, setGroqKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [todoistKey, setTodoistKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    supabase
      .from("users")
      .select("google_credentials")
      .maybeSingle()
      .then(({ data }) => {
        setGoogleStatus(data?.google_credentials ? "connected" : "disconnected");
      });
  }, []);

  const handleConnect = async () => {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return;
    window.location.href = `http://localhost:8000/auth/google?token=${token}`;
  };

  const handleContinue = () => {
    if (!groqKey.trim()) {
      setError("Groq API key is required to run the AI scan.");
      return;
    }
    sessionStorage.setItem(
      "sfm_creds",
      JSON.stringify({
        groq_api_key: groqKey.trim(),
        anthropic_api_key: anthropicKey.trim(),
        todoist_api_key: todoistKey.trim(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        calendar_ids: [],
      }),
    );
    onAdvance();
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-16"
      style={{ background: "#080810" }}
    >
      <StepDots current={0} />

      <motion.div
        variants={CONTAINER}
        initial="hidden"
        animate="show"
        className="mt-8 w-full max-w-md space-y-4"
      >
        {/* Heading */}
        <motion.div variants={ITEM} className="text-center mb-2">
          <h1
            className="font-display text-white"
            style={{
              fontSize: "clamp(1.8rem, 4vw, 2.4rem)",
              letterSpacing: "-0.025em",
            }}
          >
            Set up your AI scheduler
          </h1>
          <p className="mt-2 text-sm" style={{ color: "#94a3b8" }}>
            Connect your calendar and add your API keys to get started.
          </p>
        </motion.div>

        {/* ── Google Calendar card ──────────────────────────────────────── */}
        <motion.div variants={ITEM} className="rounded-2xl p-5" style={CARD_STYLE}>
          <div className="flex items-start gap-3">
            <div
              className="mt-0.5 p-2 rounded-lg flex-shrink-0"
              style={{ background: "rgba(99,102,241,0.15)" }}
            >
              <CalendarDays size={18} color="#6366f1" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium" style={{ color: "#f8fafc" }}>
                Google Calendar
              </p>
              <p className="text-xs mt-0.5" style={{ color: "#94a3b8" }}>
                Let the AI scan 14 days of events to learn your schedule patterns.
              </p>
              <div className="mt-3">
                {googleStatus === "loading" && (
                  <p className="text-xs" style={{ color: "#475569" }}>
                    Checking…
                  </p>
                )}
                {googleStatus === "connected" && (
                  <div
                    className="flex items-center gap-1.5 text-xs"
                    style={{ color: "#34d399" }}
                  >
                    <CheckCircle2 size={13} />
                    <span>Connected</span>
                  </div>
                )}
                {googleStatus === "disconnected" && (
                  <div className="flex items-center gap-3 flex-wrap">
                    <button
                      onClick={handleConnect}
                      className="text-xs px-3 py-1.5 rounded-lg font-medium text-white transition-all"
                      style={{
                        background: "#6366f1",
                        boxShadow: "0 0 12px rgba(99,102,241,0.35)",
                      }}
                    >
                      Connect Google
                    </button>
                    <button
                      onClick={() => setGoogleStatus("connected")}
                      className="text-xs transition-colors"
                      style={{ color: "#64748b" }}
                    >
                      Skip for now
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </motion.div>

        {/* ── API Keys card ─────────────────────────────────────────────── */}
        <motion.div
          variants={ITEM}
          className="rounded-2xl p-5 space-y-4"
          style={CARD_STYLE}
        >
          <div className="flex items-center gap-3">
            <div
              className="p-2 rounded-lg flex-shrink-0"
              style={{ background: "rgba(99,102,241,0.15)" }}
            >
              <Key size={18} color="#6366f1" />
            </div>
            <div>
              <p className="text-sm font-medium" style={{ color: "#f8fafc" }}>
                API Keys
              </p>
              <p className="text-xs" style={{ color: "#94a3b8" }}>
                Used only for your session.
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <label
                className="block text-xs font-medium mb-1.5"
                style={{ color: "#94a3b8" }}
              >
                Groq API key{" "}
                <span style={{ color: "#f43f5e" }}>*</span>
              </label>
              <input
                type="password"
                value={groqKey}
                onChange={(e) => {
                  setGroqKey(e.target.value);
                  setError(null);
                }}
                placeholder="gsk_…"
                className="w-full text-sm px-3 py-2 rounded-lg outline-none transition-shadow"
                style={{
                  ...INPUT_STYLE,
                  boxShadow: error
                    ? "0 0 0 1.5px rgba(244,63,94,0.5)"
                    : undefined,
                }}
              />
            </div>
            <div>
              <label
                className="block text-xs font-medium mb-1.5"
                style={{ color: "#94a3b8" }}
              >
                Anthropic API key{" "}
                <span style={{ color: "#475569" }}>(optional — Groq used if absent)</span>
              </label>
              <input
                type="password"
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
                placeholder="sk-ant-…"
                className="w-full text-sm px-3 py-2 rounded-lg outline-none"
                style={INPUT_STYLE}
              />
            </div>
            <div>
              <label
                className="block text-xs font-medium mb-1.5"
                style={{ color: "#94a3b8" }}
              >
                Todoist API key{" "}
                <span style={{ color: "#475569" }}>(optional for now)</span>
              </label>
              <input
                type="password"
                value={todoistKey}
                onChange={(e) => setTodoistKey(e.target.value)}
                placeholder="Your Todoist token"
                className="w-full text-sm px-3 py-2 rounded-lg outline-none"
                style={INPUT_STYLE}
              />
            </div>
          </div>
        </motion.div>

        {/* Error */}
        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-xs text-center"
            style={{ color: "#f43f5e" }}
          >
            {error}
          </motion.p>
        )}

        {/* CTA */}
        <motion.div variants={ITEM} className="pt-1">
          <button
            onClick={handleContinue}
            className="w-full py-3 rounded-xl text-sm font-medium text-white transition-all"
            style={{
              background: "#6366f1",
              boxShadow: "0 0 20px rgba(99,102,241,0.35)",
            }}
          >
            Get started →
          </button>
        </motion.div>
      </motion.div>
    </div>
  );
}
