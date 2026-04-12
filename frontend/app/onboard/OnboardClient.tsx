"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Stage0 from "./stages/Stage0";
import Stage1 from "./stages/Stage1";
import Stage2 from "./stages/Stage2";
import Stage3 from "./stages/Stage3";
import Stage4 from "./stages/Stage4";

// ── Slide transition variants ─────────────────────────────────────────────────

const PAGE = {
  initial: { opacity: 0, x: 60 },
  animate: {
    opacity: 1,
    x: 0,
    transition: { type: "spring" as const, stiffness: 80, damping: 16 },
  },
  exit: { opacity: 0, x: -60, transition: { duration: 0.2 } },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function OnboardClient() {
  const router = useRouter();
  const params = useSearchParams();
  const stage = Math.min(4, Math.max(0, Number(params.get("stage") ?? "0")));

  const advance = useCallback(() => {
    const next = Math.min(4, stage + 1);
    router.push(`/onboard?stage=${next}`);
  }, [stage, router]);

  return (
    <AnimatePresence mode="wait">
      <motion.div key={stage} {...PAGE} className="min-h-screen">
        {stage === 0 && <Stage0 onAdvance={advance} />}
        {stage === 1 && <Stage1 onAdvance={advance} />}
        {stage === 2 && <Stage2 onAdvance={advance} />}
        {stage === 3 && <Stage3 onAdvance={advance} />}
        {stage === 4 && <Stage4 />}
      </motion.div>
    </AnimatePresence>
  );
}
