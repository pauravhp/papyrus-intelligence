"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiPost } from "@/utils/api";
import StepDots from "@/components/StepDots";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Question {
  field: string;
  question: string;
  current_value: string;
  hint?: string;
}

interface Stage2Props {
  onAdvance: () => void;
}

// ── Field type inference ──────────────────────────────────────────────────────

type FieldType = "time" | "number" | "text";

function fieldType(field: string): FieldType {
  if (
    field.endsWith("_time") ||
    field.endsWith("_before") ||
    field.endsWith("_after") ||
    field.endsWith(".start") ||
    field.endsWith(".end")
  )
    return "time";
  if (field.endsWith("_minutes") || field.endsWith("_min")) return "number";
  return "text";
}

/** Strict HH:MM validation (24-hour, from <input type="time">) */
function isValidHHMM(v: string): boolean {
  return /^\d{2}:\d{2}$/.test(v);
}

/** "22:30" → "10:30 PM" for display */
function formatTime12(v: string): string {
  if (!isValidHHMM(v)) return "";
  const [h, m] = v.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

// ── Animation variants ────────────────────────────────────────────────────────

const SLIDE_IN = {
  initial: { opacity: 0, x: 40 },
  animate: {
    opacity: 1,
    x: 0,
    transition: { type: "spring" as const, stiffness: 90, damping: 14 },
  },
  exit: { opacity: 0, x: -40, transition: { duration: 0.18 } },
};

// ── Style constants ───────────────────────────────────────────────────────────

const CARD_STYLE: React.CSSProperties = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  backdropFilter: "blur(12px)",
};

const INPUT_BASE: React.CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  border: "1px solid rgba(99,102,241,0.4)",
  color: "#f8fafc",
};

// ── Constrained input ─────────────────────────────────────────────────────────

interface FieldInputProps {
  type: FieldType;
  value: string;
  onChange: (v: string) => void;
  onCommit: () => void;
  onCancel: () => void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}

function FieldInput({ type, value, onChange, onCommit, onCancel, inputRef }: FieldInputProps) {
  const base = "w-full text-sm px-3 py-2.5 rounded-lg outline-none";

  if (type === "time") {
    return (
      <div className="space-y-1">
        <input
          ref={inputRef as React.RefObject<HTMLInputElement>}
          type="time"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onCommit();
            if (e.key === "Escape") onCancel();
          }}
          className={base}
          style={{
            ...INPUT_BASE,
            colorScheme: "dark",
          }}
        />
        <p className="text-xs" style={{ color: "#475569" }}>
          Use 24-hour format — e.g. 22:30 for 10:30 PM
        </p>
      </div>
    );
  }

  if (type === "number") {
    return (
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        type="number"
        min={0}
        max={720}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onCommit();
          if (e.key === "Escape") onCancel();
        }}
        className={base}
        style={INPUT_BASE}
        placeholder="Minutes"
      />
    );
  }

  return (
    <input
      ref={inputRef as React.RefObject<HTMLInputElement>}
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onCommit();
        if (e.key === "Escape") onCancel();
      }}
      className={base}
      style={INPUT_BASE}
    />
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Stage2({ onAdvance }: Stage2Props) {
  const supabase = createClient();
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [currentIdx, setCurrentIdx] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [validationErr, setValidationErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem("sfm_stage1");
    if (!raw) return;
    const stage1 = JSON.parse(raw);
    const VALID_FIELDS = new Set([
      "sleep.default_wake_time",
      "sleep.default_sleep_time",
      "sleep.morning_buffer_minutes",
      "sleep.weekend_nothing_before",
      "calendar_rules.flamingo.color_id",
      "calendar_rules.banana.color_id",
    ]);
    const qs: Question[] = (stage1.questions_for_stage_2 ?? []).filter(
      (q: Question) => VALID_FIELDS.has(q.field),
    );
    setQuestions(qs);

    const seed: Record<string, string> = {};
    qs.forEach((q) => {
      const ft = fieldType(q.field);
      const raw = q.current_value ?? "";
      // Discard LLM natural-language values for typed fields
      if (ft === "time") {
        seed[q.field] = isValidHHMM(raw) ? raw : "";
      } else if (ft === "number") {
        seed[q.field] = /^\d+$/.test(raw.trim()) ? raw.trim() : "";
      } else {
        seed[q.field] = raw;
      }
    });
    setAnswers(seed);
  }, []);

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.focus();
  }, [editing]);

  const currentQ = questions[currentIdx];
  const isLast = currentIdx === questions.length - 1;
  const ft = currentQ ? fieldType(currentQ.field) : "text";
  const currentAnswer = currentQ ? (answers[currentQ.field] ?? "") : "";

  const handleEdit = () => {
    if (!currentQ) return;
    setDraft(currentAnswer);
    setValidationErr(null);
    setEditing(true);
  };

  const handleSaveDraft = () => {
    if (!currentQ) return;

    // Validate typed fields
    if (ft === "time" && !isValidHHMM(draft)) {
      setValidationErr("Please enter a valid time (e.g. 22:30)");
      return;
    }
    if (ft === "number" && (draft === "" || isNaN(Number(draft)))) {
      setValidationErr("Please enter a number");
      return;
    }

    setAnswers((prev) => ({ ...prev, [currentQ.field]: draft }));
    setEditing(false);
    setValidationErr(null);
    advance(draft);
  };

  const handleKeep = () => {
    if (!currentQ) return;

    // If time field has no valid value yet, force edit
    if (ft === "time" && !isValidHHMM(currentAnswer)) {
      setDraft("");
      setValidationErr(null);
      setEditing(true);
      return;
    }

    advance(currentAnswer);
  };

  const advance = async (valueForThisQ?: string) => {
    if (!isLast) {
      setCurrentIdx((i) => i + 1);
      setEditing(false);
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      if (!token) throw new Error("Not authenticated");

      const stage1 = JSON.parse(sessionStorage.getItem("sfm_stage1") ?? "{}");
      const draftConfig = stage1.proposed_config ?? {};

      // Merge the latest answer for the current question before submitting
      const finalAnswers = currentQ
        ? { ...answers, [currentQ.field]: valueForThisQ ?? currentAnswer }
        : answers;

      const answerItems = Object.entries(finalAnswers).map(([field, value]) => ({
        field,
        value,
      }));

      const result = await apiPost<{
        updated_config: Record<string, unknown>;
        answers_applied: number;
      }>("/api/onboard/stage2", { draft_config: draftConfig, answers: answerItems }, token);

      sessionStorage.setItem("sfm_stage2", JSON.stringify(result));
      onAdvance();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (questions.length === 0) {
    return (
      <div
        className="min-h-screen flex flex-col items-center justify-center px-4"
        style={{ background: "#080810" }}
      >
        <StepDots current={2} />
        <p className="mt-8 text-sm" style={{ color: "#94a3b8" }}>
          No questions to answer — all patterns detected.
        </p>
        <button
          onClick={onAdvance}
          className="mt-6 px-6 py-3 rounded-xl text-sm font-medium text-white"
          style={{ background: "#6366f1", boxShadow: "0 0 20px rgba(99,102,241,0.35)" }}
        >
          Continue →
        </button>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 py-16"
      style={{ background: "#080810" }}
    >
      <StepDots current={2} />

      <div className="mt-10 w-full max-w-md">
        {/* Progress bar */}
        <div
          className="h-0.5 w-full rounded-full mb-8 overflow-hidden"
          style={{ background: "rgba(255,255,255,0.08)" }}
        >
          <motion.div
            className="h-full rounded-full"
            style={{ background: "#6366f1" }}
            animate={{ width: `${((currentIdx + 1) / questions.length) * 100}%` }}
            transition={{ type: "spring", stiffness: 80, damping: 14 }}
          />
        </div>

        {/* Question card */}
        <AnimatePresence mode="wait">
          <motion.div
            key={currentIdx}
            {...SLIDE_IN}
            className="rounded-2xl p-6 space-y-4"
            style={CARD_STYLE}
          >
            <p className="text-xs" style={{ color: "#475569" }}>
              {currentIdx + 1} / {questions.length}
            </p>

            <p className="text-base font-medium leading-snug" style={{ color: "#f8fafc" }}>
              {currentQ?.question}
            </p>

            {/* Detected value pill */}
            {!editing && (
              <div
                className="rounded-lg px-4 py-2.5 flex items-center justify-between gap-3"
                style={{
                  background: "rgba(99,102,241,0.1)",
                  border: "1px solid rgba(99,102,241,0.25)",
                }}
              >
                <span className="text-sm" style={{ color: currentAnswer ? "#a5b4fc" : "#475569" }}>
                  {ft === "time"
                    ? (isValidHHMM(currentAnswer) ? formatTime12(currentAnswer) : "Not detected — tap Edit")
                    : (currentAnswer || "—")}
                </span>
                <button
                  onClick={handleEdit}
                  className="text-xs shrink-0"
                  style={{ color: "#6366f1" }}
                >
                  Edit
                </button>
              </div>
            )}

            {/* Constrained edit input */}
            {editing && (
              <FieldInput
                type={ft}
                value={draft}
                onChange={setDraft}
                onCommit={handleSaveDraft}
                onCancel={() => { setEditing(false); setValidationErr(null); }}
                inputRef={inputRef}
              />
            )}

            {validationErr && (
              <p className="text-xs" style={{ color: "#f43f5e" }}>
                {validationErr}
              </p>
            )}

            {currentQ?.hint && !validationErr && (
              <p className="text-xs" style={{ color: "#475569" }}>
                {currentQ.hint}
              </p>
            )}

            {/* Actions */}
            <div className="flex gap-3 pt-1">
              {editing ? (
                <button
                  onClick={handleSaveDraft}
                  className="flex-1 py-2.5 rounded-xl text-sm font-medium text-white transition-all"
                  style={{ background: "#6366f1", boxShadow: "0 0 14px rgba(99,102,241,0.3)" }}
                >
                  {isLast ? (submitting ? "Saving…" : "Save & finish") : "Save & next →"}
                </button>
              ) : (
                <button
                  onClick={handleKeep}
                  disabled={submitting}
                  className="flex-1 py-2.5 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-50"
                  style={{ background: "#6366f1", boxShadow: "0 0 14px rgba(99,102,241,0.3)" }}
                >
                  {isLast ? (submitting ? "Saving…" : "Looks right →") : "Looks right →"}
                </button>
              )}
            </div>
          </motion.div>
        </AnimatePresence>

        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-4 text-xs text-center"
            style={{ color: "#f43f5e" }}
          >
            {error}
          </motion.p>
        )}
      </div>
    </div>
  );
}
