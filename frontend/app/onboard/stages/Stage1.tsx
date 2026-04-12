"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiPost } from "@/utils/api";
import StepDots from "@/components/StepDots";

const ScanOrbit = dynamic(() => import("./ScanOrbit"), { ssr: false });

// ── Types ─────────────────────────────────────────────────────────────────────

type Phase = "loading" | "done" | "error";

interface Stage1Props {
  onAdvance: () => void;
}

// ── Ellipsis animation ────────────────────────────────────────────────────────

function Ellipsis() {
  const [dots, setDots] = useState(".");
  useEffect(() => {
    const id = setInterval(
      () => setDots((d) => (d.length >= 3 ? "." : d + ".")),
      420,
    );
    return () => clearInterval(id);
  }, []);
  return <span style={{ color: "#6366f1", letterSpacing: "0.08em" }}>{dots}</span>;
}

// ── Stat pill ─────────────────────────────────────────────────────────────────

function Pill({ label }: { label: string }) {
  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.85, y: 8 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 120, damping: 14 }}
      className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium"
      style={{
        background: "rgba(99,102,241,0.18)",
        border: "1px solid rgba(99,102,241,0.35)",
        color: "#a5b4fc",
      }}
    >
      {label}
    </motion.span>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Stage1({ onAdvance }: Stage1Props) {
  const supabase = createClient();
  const [phase, setPhase] = useState<Phase>("loading");
  const [orbCount, setOrbCount] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pills, setPills] = useState<string[]>([]);
  const [showCTA, setShowCTA] = useState(false);
  const calledRef = useRef(false);

  // Increment orbs while loading (up to 12, one per 600ms)
  useEffect(() => {
    if (phase !== "loading") return;
    const id = setInterval(() => {
      setOrbCount((n) => {
        if (n >= 12) {
          clearInterval(id);
          return n;
        }
        return n + 1;
      });
    }, 600);
    return () => clearInterval(id);
  }, [phase]);

  // Fire stage1 API call once
  useEffect(() => {
    if (calledRef.current) return;
    calledRef.current = true;

    (async () => {
      try {
        const { data: sessionData } = await supabase.auth.getSession();
        const token = sessionData.session?.access_token;
        if (!token) throw new Error("Not authenticated");

        const raw = sessionStorage.getItem("sfm_creds");
        if (!raw) throw new Error("Missing credentials from Stage 0");
        const creds = JSON.parse(raw);

        const result = await apiPost<{
          proposed_config: Record<string, unknown>;
          questions_for_stage_2: unknown[];
        }>("/api/onboard/stage1", creds, token);

        sessionStorage.setItem("sfm_stage1", JSON.stringify(result));

        // Build pattern pills
        const config = result.proposed_config as Record<string, Record<string, unknown>>;
        const wake =
          (config?.sleep as Record<string, unknown>)?.default_wake_time ?? null;
        const qCount = result.questions_for_stage_2.length;
        const newPills = [
          "14 days scanned",
          wake ? `Wake ~${wake}` : null,
          qCount > 0 ? `${qCount} questions to refine` : null,
        ].filter(Boolean) as string[];
        setPills(newPills);

        setPhase("done");
        setOrbCount(12);

        // Show heading + CTA after 1.5s
        setTimeout(() => setShowCTA(true), 1500);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setErrorMsg(msg);
        setPhase("error");
      }
    })();
  }, []);

  return (
    <div
      className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden"
      style={{ background: "#080810" }}
    >
      {/* 3D scene — full viewport background */}
      <div className="absolute inset-0 z-0">
        <ScanOrbit isLoading={phase === "loading"} orbCount={orbCount} />
      </div>

      {/* Overlay UI */}
      <div className="relative z-10 flex flex-col items-center text-center px-6 pointer-events-none">
        <StepDots current={1} />

        <div className="mt-10 space-y-4">
          <AnimatePresence mode="wait">
            {phase === "loading" && (
              <motion.p
                key="scanning"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="text-lg font-medium"
                style={{ color: "#cbd5e1" }}
              >
                Scanning your calendar
                <Ellipsis />
              </motion.p>
            )}

            {phase === "error" && (
              <motion.div
                key="error"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-2"
              >
                <p className="text-sm" style={{ color: "#f43f5e" }}>
                  {errorMsg ?? "Something went wrong."}
                </p>
                <button
                  className="text-xs underline pointer-events-auto"
                  style={{ color: "#6366f1" }}
                  onClick={() => window.location.reload()}
                >
                  Try again
                </button>
              </motion.div>
            )}

            {phase === "done" && (
              <motion.div
                key="done"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-5"
              >
                {/* Pills */}
                <motion.div
                  className="flex flex-wrap justify-center gap-2"
                  initial="hidden"
                  animate="show"
                  variants={{ show: { transition: { staggerChildren: 0.12 } }, hidden: {} }}
                >
                  {pills.map((p) => (
                    <Pill key={p} label={p} />
                  ))}
                </motion.div>

                <AnimatePresence>
                  {showCTA && (
                    <motion.div
                      initial={{ opacity: 0, y: 16 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ type: "spring", stiffness: 90, damping: 14 }}
                      className="space-y-4"
                    >
                      <h2
                        className="font-display"
                        style={{
                          fontSize: "clamp(1.6rem, 4vw, 2.4rem)",
                          color: "#f8fafc",
                          letterSpacing: "-0.025em",
                        }}
                      >
                        Here&apos;s what I found.
                      </h2>
                      <button
                        onClick={onAdvance}
                        className="pointer-events-auto inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-medium text-white transition-all"
                        style={{
                          background: "#6366f1",
                          boxShadow: "0 0 20px rgba(99,102,241,0.4)",
                        }}
                      >
                        See your insights →
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
