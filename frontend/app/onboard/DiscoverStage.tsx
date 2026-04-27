"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiPost } from "@/utils/api";
import ColorRuleCard from "@/components/ColorRuleCard";
import FieldTooltip from "@/components/FieldTooltip";
import {
  ColorRule,
  DEFAULT_CATEGORIES,
  categoriesToCalendarRules,
  clearDuplicateColor,
} from "@/lib/gcalColors";

interface DiscoverStageProps {
  timezone: string;
  calendarIds: string[];
  onComplete: () => void;
}

interface DetectedCategory {
  name: string;
  color_name: string;
  color_id: string | null;
  event_samples: string[];
  buffer_before_minutes: number;
  buffer_after_minutes: number;
}

// Local extension: embeds the scan hint directly in the category object
// so it survives deletions/reordering without index drift.
type CategoryWithHint = ColorRule & { hint?: string }

type Phase = "scanning" | "review" | "confirming" | "error";

const LABEL: CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 4,
  display: "block",
};

const INPUT: CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 8,
  padding: "10px 10px",
  minHeight: 40,
  fontSize: 16,
  outline: "none",
  width: "100%",
  fontFamily: "var(--font-literata)",
};

const SECTION_HEADING: CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  marginBottom: 12,
};

export default function DiscoverStage({ timezone, calendarIds, onComplete }: DiscoverStageProps) {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;
  const [phase, setPhase] = useState<Phase>("scanning");
  const [retryCount, setRetryCount] = useState(0);
  const [proposedConfig, setProposedConfig] = useState<Record<string, unknown>>({});
  const [categories, setCategories] = useState<CategoryWithHint[]>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [confirmError, setConfirmError] = useState<string | null>(null);

  // sleep & scheduling draft (kept separate from categories)
  const [sleep, setSleep] = useState<Record<string, unknown>>({});
  const [scheduling, setScheduling] = useState<Record<string, unknown>>({});

  useEffect(() => {
    let cancelled = false;
    const runScan = async () => {
      try {
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token ?? "";
        const result = await apiPost<{
          proposed_config: Record<string, unknown>;
          questions: unknown[];
          detected_categories: DetectedCategory[];
        }>(
          "/api/onboard/scan",
          { timezone, calendar_ids: calendarIds },
          token,
        );
        if (!cancelled) {
          setProposedConfig(result.proposed_config);
          setSleep((result.proposed_config.sleep as Record<string, unknown>) ?? {});
          setScheduling((result.proposed_config.scheduling as Record<string, unknown>) ?? {});

          // Populate categories from detected_categories or fall back to defaults
          const detected = result.detected_categories ?? [];
          if (detected.length > 0) {
            const cats: CategoryWithHint[] = detected.map(d => ({
              name: d.name,
              colorId: d.color_id,
              bufferBefore: ([0, 5, 15, 30].includes(d.buffer_before_minutes)
                ? d.buffer_before_minutes : 15) as 0 | 5 | 15 | 30,
              bufferAfter: ([0, 5, 15, 30].includes(d.buffer_after_minutes)
                ? d.buffer_after_minutes : 15) as 0 | 5 | 15 | 30,
              hint: d.event_samples.length > 0
                ? `Detected · ${d.event_samples.slice(0, 3).join(", ")}`
                : undefined,
            }));
            setCategories(cats);
          } else {
            setCategories([...DEFAULT_CATEGORIES]);
          }
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
  }, [timezone, calendarIds, retryCount]);

  const handleCategoryChange = (index: number, updated: ColorRule) => {
    setCategories(prev => {
      let next = [...prev] as CategoryWithHint[];
      // Enforce duplicate color constraint
      if (updated.colorId !== null && updated.colorId !== prev[index].colorId) {
        next = clearDuplicateColor(next, updated.colorId, index) as CategoryWithHint[];
      }
      next[index] = { ...next[index], ...updated };
      return next;
    });
  };

  const handleCategoryDelete = (index: number) => {
    setCategories(prev => prev.filter((_, i) => i !== index));
  };

  const handleAddCategory = () => {
    setCategories(prev => [
      ...prev,
      { name: "", colorId: null, bufferBefore: 15, bufferAfter: 15 },
    ]);
  };

  const canConfirm = categories.every(c => c.name.trim() !== "");

  const handleConfirm = async () => {
    if (!canConfirm) return;
    setPhase("confirming");
    setConfirmError(null);
    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";
      const config = {
        ...proposedConfig,
        sleep,
        scheduling,
        calendar_rules: categoriesToCalendarRules(categories),
      };
      await apiPost("/api/onboard/promote", { config }, token);
      onComplete();
    } catch (e) {
      setPhase("review");
      setConfirmError((e as Error).message);
    }
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-16"
      style={{ background: "var(--bg)" }}
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
            <div style={{ display: "flex", justifyContent: "center", gap: 6, marginBottom: 24 }}>
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  animate={{ scale: [1, 1.4, 1], opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }}
                  style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)" }}
                />
              ))}
            </div>
            <h2
              className="font-display"
              style={{ fontSize: "1.6rem", color: "var(--text)", letterSpacing: "-0.02em" }}
            >
              Learning your schedule
            </h2>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 8 }}>
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
            className="onboard-card-pad"
            style={{
              width: "calc(100% - 32px)",
              maxWidth: 480,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 20,
            }}
          >
            <h2
              className="font-display"
              style={{ fontSize: "1.4rem", color: "var(--text)", marginBottom: 4, letterSpacing: "-0.02em" }}
            >
              Here&apos;s what I found
            </h2>
            <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
              Review and adjust — this becomes your scheduling config.
            </p>

            {confirmError && (
              <p style={{ color: "var(--danger)", fontSize: 12, marginBottom: 12 }}>{confirmError}</p>
            )}

            {/* Sleep & Schedule */}
            <p style={SECTION_HEADING}>Sleep &amp; Schedule</p>
            <div className="onboard-grid-2" style={{ marginBottom: 20 }}>
              {[
                { label: "Wake time", key: "default_wake_time", type: "time", tooltip: undefined },
                {
                  label: "Morning buffer (min)",
                  key: "morning_buffer_minutes",
                  type: "number",
                  tooltip: "Time you protect after waking before any task begins. For coffee, a walk, easing in.",
                },
                {
                  label: "First task not before",
                  key: "first_task_not_before",
                  type: "time",
                  tooltip: "A hard floor. No task will be scheduled before this, even if your morning buffer ends earlier.",
                },
                {
                  label: "No tasks after",
                  key: "no_tasks_after",
                  type: "time",
                  tooltip: "Your wind-down boundary. No tasks or meetings will be scheduled past this time.",
                },
              ].map(({ label, key, type, tooltip }) => (
                <div key={key} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 5 }}>
                    <label style={{ ...LABEL, marginBottom: 0 }}>{label}</label>
                    {tooltip && <FieldTooltip content={tooltip} />}
                  </div>
                  <input
                    type={type}
                    value={(sleep[key] as string | number) ?? ""}
                    onChange={e => setSleep(s => ({
                      ...s,
                      [key]: type === "number" ? parseInt(e.target.value, 10) || 0 : e.target.value,
                    }))}
                    style={INPUT}
                  />
                </div>
              ))}
            </div>

            {/* Event categories */}
            <p style={{ ...SECTION_HEADING, marginTop: 4 }}>Event categories</p>
            <p style={{ fontSize: 12, color: "var(--text-faint)", fontStyle: "italic", marginBottom: 14 }}>
              I spotted these colour patterns in your last 14 days — rename them to match how you think about your calendar.
            </p>

            {categories.map((cat, i) => (
              <ColorRuleCard
                key={i}
                rule={cat}
                detectedHint={cat.hint}
                onChange={updated => handleCategoryChange(i, updated)}
                onDelete={() => handleCategoryDelete(i)}
              />
            ))}

            <button
              onClick={handleAddCategory}
              style={{
                width: "100%",
                padding: 11,
                borderRadius: 10,
                border: "1px dashed var(--border-strong)",
                background: "transparent",
                color: "var(--text-faint)",
                fontSize: 13,
                cursor: "pointer",
                marginTop: 4,
                fontFamily: "var(--font-literata)",
              }}
            >
              + Add event category
            </button>

            {/* Scheduling */}
            <p style={{ ...SECTION_HEADING, marginTop: 20 }}>Scheduling</p>
            <div className="onboard-grid-2">
              {[
                {
                  label: "Min gap (min)",
                  key: "min_gap_between_tasks_minutes",
                  type: "number",
                  tooltip: "Breathing room between tasks. Time to transition, think, or just exist between blocks.",
                },
                {
                  label: "Max tasks / day",
                  key: "max_tasks_per_day",
                  type: "number",
                  tooltip: "The most tasks Papyrus will schedule in one day. Keeps your plan realistic, not aspirational.",
                },
              ].map(({ label, key, type, tooltip }) => (
                <div key={key} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 5 }}>
                    <label style={{ ...LABEL, marginBottom: 0 }}>{label}</label>
                    {tooltip && <FieldTooltip content={tooltip} />}
                  </div>
                  <input
                    type={type}
                    value={(scheduling[key] as number) ?? ""}
                    onChange={e => setScheduling(s => ({
                      ...s,
                      [key]: parseInt(e.target.value, 10) || 0,
                    }))}
                    style={INPUT}
                  />
                </div>
              ))}
            </div>

            <motion.button
              onClick={handleConfirm}
              disabled={!canConfirm || phase === "confirming"}
              whileHover={canConfirm ? { scale: 1.01 } : undefined}
              whileTap={canConfirm ? { scale: 0.99 } : undefined}
              style={{
                marginTop: 20,
                width: "100%",
                padding: "12px 0",
                borderRadius: 12,
                background: canConfirm ? "var(--accent)" : "var(--accent-tint)",
                color: canConfirm ? "var(--bg)" : "var(--accent)",
                border: "none",
                fontSize: 14,
                fontWeight: 500,
                cursor: canConfirm ? "pointer" : "not-allowed",
              }}
            >
              {phase === "confirming" ? "Setting up…" : "Confirm setup →"}
            </motion.button>
          </motion.div>
        )}

        {phase === "error" && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{ textAlign: "center", maxWidth: 400 }}
          >
            <p style={{ color: "var(--danger)", fontSize: 14, marginBottom: 12 }}>
              Scan failed: {errorMsg}
            </p>
            <motion.button
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.96 }}
              onClick={() => { setPhase("scanning"); setRetryCount(c => c + 1); }}
              style={{
                background: "var(--accent)",
                color: "var(--bg)",
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
