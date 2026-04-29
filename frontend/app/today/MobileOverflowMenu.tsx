"use client";

import { motion, AnimatePresence } from "framer-motion";

interface MenuItem {
  label: string;
  onSelect: () => void;
  emphasis?: "primary" | "default";
}

interface Props {
  open: boolean;
  items: MenuItem[];
  onClose: () => void;
}

export default function MobileOverflowMenu({ open, items, onClose }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(44,26,14,0.4)",
              zIndex: 50,
            }}
          />
          <motion.div
            key="sheet"
            data-testid="overflow-sheet"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            style={{
              position: "fixed",
              left: 0,
              right: 0,
              bottom: 0,
              background: "var(--surface)",
              borderTopLeftRadius: 18,
              borderTopRightRadius: 18,
              padding: "12px 16px calc(16px + env(safe-area-inset-bottom))",
              zIndex: 51,
              boxShadow: "0 -6px 24px rgba(44,26,14,0.18)",
            }}
          >
            <div style={{ width: 36, height: 4, borderRadius: 99, background: "rgba(44,26,14,0.25)", margin: "0 auto 12px" }} />
            {items.map((it) => (
              <button
                key={it.label}
                type="button"
                onClick={() => { it.onSelect(); onClose(); }}
                style={{
                  width: "100%",
                  textAlign: "left",
                  background: "transparent",
                  border: "none",
                  padding: "14px 4px",
                  fontFamily: "var(--font-literata)",
                  fontSize: 14,
                  color: it.emphasis === "primary" ? "var(--accent)" : "var(--text)",
                  borderBottom: "1px solid rgba(44,26,14,0.08)",
                  minHeight: 48,
                }}
              >
                {it.label}
              </button>
            ))}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
