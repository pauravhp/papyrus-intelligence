"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

interface Props {
  onClose: () => void;
  children: React.ReactNode;
}

type Snap = "low" | "high";

const SNAP_VH: Record<Snap, number> = { low: 45, high: 85 };

export default function MobilePlanningSheet({ onClose, children }: Props) {
  const [snap, setSnap] = useState<Snap>("low");
  const ref = useRef<HTMLDivElement>(null);

  // Listen for any inner textarea/input focus → snap high; blur → snap low.
  // focus events bubble (focusin/focusout) so a single root listener works for
  // every input the wrapped panel renders, current and future.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onFocusIn = (e: FocusEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) {
        setSnap("high");
      }
    };
    const onFocusOut = (e: FocusEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) {
        setSnap("low");
      }
    };
    el.addEventListener("focusin", onFocusIn);
    el.addEventListener("focusout", onFocusOut);
    return () => {
      el.removeEventListener("focusin", onFocusIn);
      el.removeEventListener("focusout", onFocusOut);
    };
  }, []);

  return (
    <>
      <motion.div
        key="scrim"
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.35 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(44,26,14,1)", zIndex: 40 }}
      />
      <motion.div
        ref={ref}
        data-testid="mobile-planning-sheet"
        data-snap={snap}
        initial={{ y: "100%" }}
        animate={{ y: `${100 - SNAP_VH[snap]}vh` }}
        exit={{ y: "100%" }}
        transition={{ type: "spring", stiffness: 280, damping: 28 }}
        drag="y"
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={0.18}
        onDragEnd={(_, info) => {
          if (info.offset.y > 120) onClose();
        }}
        style={{
          position: "fixed",
          left: 0,
          right: 0,
          top: 0,
          height: "100vh",
          zIndex: 41,
          background: "var(--surface)",
          borderTopLeftRadius: 18,
          borderTopRightRadius: 18,
          boxShadow: "0 -10px 32px rgba(44,26,14,0.18)",
          display: "flex",
          flexDirection: "column",
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "center", padding: "8px 0 4px" }}>
          <span style={{ width: 36, height: 4, borderRadius: 99, background: "rgba(44,26,14,0.25)" }} />
        </div>
        <button
          type="button"
          aria-label="Dismiss planning"
          onClick={onClose}
          style={{
            position: "absolute",
            top: 8,
            right: 12,
            width: 32,
            height: 32,
            background: "transparent",
            border: "none",
            color: "var(--text-faint)",
            fontSize: 18,
            cursor: "pointer",
          }}
        >
          ✕
        </button>
        <div style={{ flex: 1, overflowY: "auto" }}>{children}</div>
      </motion.div>
    </>
  );
}
