// frontend/app/onboard/DiscoverStage.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiPost } from "@/utils/api";
import ConfigCard from "@/components/ConfigCard";

interface DiscoverStageProps {
  timezone: string;
  calendarIds: string[];
  onComplete: () => void;
}

type Phase = "scanning" | "review" | "confirming" | "error";

export default function DiscoverStage({ timezone, calendarIds, onComplete }: DiscoverStageProps) {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;
  const [phase, setPhase] = useState<Phase>("scanning");
  const [proposedConfig, setProposedConfig] = useState<Record<string, unknown>>({});
  const [errorMsg, setErrorMsg] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const runScan = async () => {
      try {
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token ?? "";
        const result = await apiPost<{ proposed_config: Record<string, unknown>; questions: unknown[] }>(
          "/api/onboard/scan",
          { timezone, calendar_ids: calendarIds },
          token,
        );
        if (!cancelled) {
          setProposedConfig(result.proposed_config);
          setPhase("review");
        }
      } catch (e) {
        if (!cancelled) {
          setErrorMsg((e as Error).message);
          setPhase("error");
        }
      }
    };
    runScan();
    return () => { cancelled = true; };
  }, [timezone, calendarIds]);

  const handleConfirm = async (updatedConfig: Record<string, unknown>) => {
    setPhase("confirming");
    setConfirmError(null);
    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";
      await apiPost("/api/onboard/promote", { config: updatedConfig }, token);
      onComplete();
    } catch (e) {
      setPhase("review");
      setConfirmError((e as Error).message);
    }
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-16"
      style={{ background: "#080810" }}
    >
      <AnimatePresence mode="wait">
        {phase === "scanning" && (
          <motion.div
            key="scanning"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{ textAlign: "center", maxWidth: 400 }}
          >
            {/* Minimal pulse indicator */}
            <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBottom: 24 }}>
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  animate={{ scale: [1, 1.4, 1], opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
                  style={{ width: 8, height: 8, borderRadius: "50%", background: "#6366f1" }}
                />
              ))}
            </div>
            <h2
              className="font-display"
              style={{ fontSize: "1.6rem", color: "#f8fafc", letterSpacing: "-0.02em" }}
            >
              Learning your schedule
            </h2>
            <p style={{ color: "#64748b", fontSize: 13, marginTop: 8 }}>
              Scanning the last 14 days to understand your patterns…
            </p>
          </motion.div>
        )}

        {(phase === "review" || phase === "confirming") && (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 100, damping: 16 }}
            style={{
              width: "calc(100% - 32px)",
              maxWidth: 480,
              background: "rgba(255,255,255,0.03)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 20,
              padding: "28px 28px 24px",
            }}
          >
            <h2
              className="font-display"
              style={{ fontSize: "1.4rem", color: "#f8fafc", marginBottom: 4, letterSpacing: "-0.02em" }}
            >
              Here's what I found
            </h2>
            <p style={{ color: "#64748b", fontSize: 13, marginBottom: 20 }}>
              Review and adjust — this becomes your scheduling config.
            </p>
            {confirmError && (
              <p style={{ color: "#f43f5e", fontSize: 12, marginBottom: 12 }}>{confirmError}</p>
            )}
            <ConfigCard
              config={proposedConfig}
              onSave={handleConfirm}
              saveLabel={phase === "confirming" ? "Setting up…" : "Confirm setup →"}
            />
          </motion.div>
        )}

        {phase === "error" && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{ textAlign: "center", maxWidth: 400 }}
          >
            <p style={{ color: "#f43f5e", fontSize: 14, marginBottom: 12 }}>
              Scan failed: {errorMsg}
            </p>
            <motion.button
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.96 }}
              onClick={() => setPhase("scanning")}
              style={{
                background: "#6366f1",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "8px 20px",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              Retry
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
