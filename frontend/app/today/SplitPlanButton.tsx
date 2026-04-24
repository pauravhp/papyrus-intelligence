"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface SplitPlanButtonProps {
  confirmed: boolean;   // true → label is "Refine", false → "Plan today"
  disabled?: boolean;
  onPlan: (contextNote?: string, target?: "today" | "tomorrow") => void;
}

export default function SplitPlanButton({ confirmed, disabled, onPlan }: SplitPlanButtonProps) {
  const [contextOpen, setContextOpen] = useState(false);
  const [contextNote, setContextNote] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const label = confirmed ? "Refine" : "Plan today";

  useEffect(() => {
    if (contextOpen) inputRef.current?.focus();
  }, [contextOpen]);

  useEffect(() => {
    if (disabled) { setContextOpen(false); setContextNote(""); }
  }, [disabled]);

  const handleMainClick = () => {
    if (disabled) return;
    // Refine requires context. Pressing the main button reveals the input
    // instead of firing a blind re-plan on the already-confirmed schedule.
    if (confirmed) {
      setContextOpen(true);
      return;
    }
    setContextOpen(false);
    setContextNote("");
    onPlan(undefined);
  };

  const handleChevronClick = () => {
    if (disabled) return;
    setContextOpen((prev) => !prev);
  };

  const handleSubmitContext = () => {
    const note = contextNote.trim();
    // Refine requires an actual instruction — no blind regenerate.
    if (confirmed && !note) return;
    setContextOpen(false);
    setContextNote("");
    onPlan(note || undefined, "today");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSubmitContext();
    if (e.key === "Escape") setContextOpen(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
      {/* Button row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <button
        onClick={() => { if (!disabled) onPlan(undefined, "tomorrow"); }}
        disabled={disabled}
        style={{
          padding: "8px 14px",
          background: "transparent",
          color: "var(--text-muted)",
          border: "1px solid var(--border-strong)",
          borderRadius: 10,
          fontFamily: "var(--font-literata)",
          fontSize: 13,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
          letterSpacing: "0.01em",
        }}
      >
        Plan tomorrow
      </button>
      <div
        style={{
          display: "flex",
          borderRadius: 10,
          overflow: "hidden",
          border: "1px solid rgba(196,130,26,0.30)",
          opacity: disabled ? 0.5 : 1,
        }}
      >
        {/* Main area */}
        <button
          onClick={handleMainClick}
          disabled={disabled}
          style={{
            padding: "8px 16px",
            background: "var(--accent)",
            color: "var(--bg)",
            border: "none",
            fontFamily: "var(--font-literata)",
            fontSize: 13,
            cursor: disabled ? "not-allowed" : "pointer",
            letterSpacing: "0.01em",
          }}
        >
          {label}
        </button>
        {/* Chevron — reveals context field */}
        <button
          onClick={handleChevronClick}
          disabled={disabled}
          aria-label="Add context before planning"
          style={{
            padding: "8px 10px",
            background: contextOpen ? "var(--accent-hover)" : "var(--accent)",
            color: "var(--bg)",
            border: "none",
            borderLeft: "1px solid rgba(245,239,224,0.2)",
            cursor: disabled ? "not-allowed" : "pointer",
            fontSize: 10,
            display: "flex",
            alignItems: "center",
            transition: "background 0.15s",
          }}
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
            <path d="M1 3l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
          </svg>
        </button>
      </div>
      </div>

      {/* Inline context field */}
      <AnimatePresence>
        {contextOpen && (
          <motion.div
            initial={{ opacity: 0, y: -4, height: 0 }}
            animate={{ opacity: 1, y: 0, height: "auto" }}
            exit={{ opacity: 0, y: -4, height: 0 }}
            transition={{ duration: 0.18 }}
            style={{ overflow: "hidden" }}
          >
            <div
              style={{
                display: "flex",
                gap: 6,
                alignItems: "center",
                background: "var(--surface)",
                border: "1px solid var(--border-strong)",
                borderRadius: 9,
                padding: "6px 8px 6px 12px",
                width: 280,
              }}
            >
              <input
                ref={inputRef}
                type="text"
                value={contextNote}
                onChange={(e) => setContextNote(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={confirmed ? "Move gym to 7am, drop the LinkedIn post…" : "Tired today, travelling, light day…"}
                disabled={disabled}
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  fontFamily: "var(--font-literata)",
                  fontSize: 12,
                  color: "var(--text)",
                }}
              />
              <button
                onClick={handleSubmitContext}
                disabled={disabled}
                style={{
                  padding: "4px 10px",
                  background: "var(--accent)",
                  color: "var(--bg)",
                  border: "none",
                  borderRadius: 6,
                  fontFamily: "var(--font-literata)",
                  fontSize: 12,
                  cursor: disabled ? "not-allowed" : "pointer",
                  flexShrink: 0,
                }}
              >
                {confirmed ? "Refine →" : "Plan →"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
