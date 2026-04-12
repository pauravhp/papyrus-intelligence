"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import StepDots from "@/components/StepDots";
import { useRouter } from "next/navigation";

const ScanOrbit = dynamic(() => import("./ScanOrbit"), { ssr: false });

// ── Word-by-word stagger ──────────────────────────────────────────────────────

const HEADLINE = "Your schedule is ready.";
const WORDS = HEADLINE.split(" ");

const WORD_VARIANTS = {
  hidden: { opacity: 0, y: 20 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      delay: 0.3 + i * 0.12,
      type: "spring" as const,
      stiffness: 90,
      damping: 14,
    },
  }),
};

const SUB_VARIANTS = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      delay: 0.3 + WORDS.length * 0.12 + 0.3,
      type: "spring" as const,
      stiffness: 80,
      damping: 14,
    },
  },
};

const CTA_VARIANTS = {
  hidden: { opacity: 0, scale: 0.95 },
  show: {
    opacity: 1,
    scale: 1,
    transition: {
      delay: 0.3 + WORDS.length * 0.12 + 0.7,
      type: "spring" as const,
      stiffness: 80,
      damping: 14,
    },
  },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function Stage4() {
  const router = useRouter();
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    // Small delay so the canvas mounts first
    const id = setTimeout(() => setAnimate(true), 80);
    return () => clearTimeout(id);
  }, []);

  return (
    <div
      className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden"
      style={{ background: "#080810" }}
    >
      {/* Stable orbit (not loading) */}
      <div className="absolute inset-0 z-0">
        <ScanOrbit isLoading={false} orbCount={12} />
      </div>

      {/* Overlay */}
      <div className="relative z-10 flex flex-col items-center text-center px-6">
        <StepDots current={4} total={4} />

        <motion.div
          className="mt-10 space-y-5"
          initial="hidden"
          animate={animate ? "show" : "hidden"}
        >
          {/* Word-by-word headline */}
          <h1
            className="font-display"
            style={{
              fontSize: "clamp(2rem, 5vw, 3rem)",
              letterSpacing: "-0.03em",
              color: "#f8fafc",
              lineHeight: 1.15,
            }}
          >
            {WORDS.map((word, i) => (
              <motion.span
                key={i}
                custom={i}
                variants={WORD_VARIANTS}
                className="inline-block mr-[0.25em]"
                style={{
                  color: word === "ready." ? "#818cf8" : "#f8fafc",
                }}
              >
                {word}
              </motion.span>
            ))}
          </h1>

          {/* Subtext */}
          <motion.p variants={SUB_VARIANTS} style={{ color: "#94a3b8", fontSize: 14 }}>
            Head to your dashboard to plan your first day.
          </motion.p>

          {/* CTA */}
          <motion.div variants={CTA_VARIANTS}>
            <button
              onClick={() => router.push("/dashboard")}
              className="inline-flex items-center gap-2 px-8 py-3.5 rounded-xl text-sm font-medium text-white transition-all"
              style={{
                background: "#6366f1",
                boxShadow: "0 0 28px rgba(99,102,241,0.45)",
              }}
            >
              Go to dashboard →
            </button>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}
