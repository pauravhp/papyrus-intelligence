"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";

export type ToastTone = "success" | "error";

export interface ToastState {
  message: string;
  tone?: ToastTone;
}

interface ToastProps {
  toast: ToastState | null;
  onDismiss: () => void;
  /** Auto-dismiss duration in ms. Defaults to 2000. */
  durationMs?: number;
}

export default function Toast({ toast, onDismiss, durationMs = 2000 }: ToastProps) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, durationMs);
    return () => clearTimeout(t);
  }, [toast, onDismiss, durationMs]);

  return (
    <div
      aria-live="polite"
      style={{
        position: "fixed",
        right: 24,
        bottom: 24,
        zIndex: 50,
        pointerEvents: "none",
      }}
    >
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.message + (toast.tone ?? "success")}
            role="status"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ type: "spring", stiffness: 320, damping: 28 }}
            style={{
              padding: "10px 16px",
              minWidth: 160,
              maxWidth: 340,
              borderRadius: 10,
              fontFamily: "var(--font-literata)",
              fontSize: 13,
              lineHeight: 1.4,
              color:
                toast.tone === "error" ? "var(--danger, #b04a3a)" : "var(--accent)",
              background:
                toast.tone === "error"
                  ? "rgba(176, 74, 58, 0.08)"
                  : "var(--accent-tint)",
              border: `1px solid ${
                toast.tone === "error"
                  ? "rgba(176, 74, 58, 0.32)"
                  : "rgba(196,130,26,0.22)"
              }`,
              boxShadow: "0 6px 20px rgba(40, 28, 14, 0.12)",
              pointerEvents: "auto",
            }}
          >
            {toast.message}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
