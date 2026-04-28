// frontend/app/dashboard/rhythms/RhythmPanel.tsx
"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import type { Rhythm } from "./RhythmCard";
import FieldTooltip from "@/components/FieldTooltip";

export interface RhythmFormData {
  name: string;
  description: string;
  sessions_per_week: number;
  session_min: number;
  session_max: number;
  end_date: string;
  days_of_week: string[];
}

const ALL_DAYS: { key: string; short: string }[] = [
  { key: "monday",    short: "M" },
  { key: "tuesday",   short: "T" },
  { key: "wednesday", short: "W" },
  { key: "thursday",  short: "T" },
  { key: "friday",    short: "F" },
  { key: "saturday",  short: "S" },
  { key: "sunday",    short: "S" },
];

// 15-min increments from 15 → 240 (4 hours). Matches the ultradian cap
// referenced elsewhere in CLAUDE.md.
const DURATION_OPTIONS: number[] = Array.from({ length: 16 }, (_, i) => 15 * (i + 1));

interface Props {
  open: boolean;
  rhythm: Rhythm | null; // null = add mode, non-null = edit mode
  onClose: () => void;
  onSave: (data: RhythmFormData) => Promise<void>;
}

function Stepper({
  value,
  min,
  max,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  const btnStyle: React.CSSProperties = {
    width: 40,
    height: 38,
    border: "none",
    background: "transparent",
    color: "var(--text-muted)",
    cursor: "pointer",
    fontSize: 18,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    fontFamily: "var(--font-literata)",
    transition: "background 0.12s",
  };
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        background: "var(--surface-raised)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        overflow: "hidden",
        width: "100%",
      }}
    >
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - 1))}
        style={btnStyle}
      >
        −
      </button>
      <div
        style={{
          flex: 1,
          textAlign: "center",
          fontFamily: "var(--font-gilda)",
          fontSize: 15,
          color: "var(--text)",
          borderLeft: "1px solid var(--border)",
          borderRight: "1px solid var(--border)",
          height: 38,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {value}
      </div>
      <button
        type="button"
        onClick={() => onChange(Math.min(max, value + 1))}
        style={btnStyle}
      >
        +
      </button>
    </div>
  );
}

const LABEL: React.CSSProperties = {
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.09em",
  color: "var(--text-muted)",
  display: "block",
  marginBottom: 6,
};

const INPUT: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "9px 12px",
  fontFamily: "var(--font-literata)",
  fontSize: 13,
  color: "var(--text)",
  outline: "none",
  width: "100%",
};

export default function RhythmPanel({ open, rhythm, onClose, onSave }: Props) {
  const isEdit = rhythm !== null;

  // Snap to nearest 15-min increment, clamped to [15, 240].
  const snap15 = (m: number): number => {
    const rounded = Math.round(m / 15) * 15;
    return Math.max(15, Math.min(240, rounded));
  };

  const defaultForm = (): RhythmFormData => ({
    name: rhythm?.rhythm_name ?? "",
    description: rhythm?.description ?? "",
    sessions_per_week: rhythm?.sessions_per_week ?? 3,
    session_min: snap15(rhythm?.session_min_minutes ?? 30),
    session_max: snap15(rhythm?.session_max_minutes ?? 60),
    end_date: rhythm?.end_date ?? "",
    // New rhythms default to all days; existing rhythms with NULL → all days
    // for the form (we still send the explicit array on save).
    days_of_week:
      rhythm?.days_of_week && rhythm.days_of_week.length > 0
        ? rhythm.days_of_week
        : ALL_DAYS.map((d) => d.key),
  });

  const [form, setForm] = useState<RhythmFormData>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form whenever panel opens / rhythm changes
  useEffect(() => {
    if (open) {
      setForm(defaultForm());
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rhythm?.id]);

  // Escape key closes panel
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    if (form.days_of_week.length === 0) {
      setError("Pick at least one day for this rhythm.");
      return;
    }
    // Ensure min <= max
    const corrected: RhythmFormData = {
      ...form,
      description: form.description.trim(),
      session_min: Math.min(form.session_min, form.session_max),
      session_max: Math.max(form.session_min, form.session_max),
    };
    setSaving(true);
    setError(null);
    try {
      await onSave(corrected);
    } catch {
      setError("Couldn't save — check your connection and try again.");
    } finally {
      setSaving(false);
    }
  };

  const set = <K extends keyof RhythmFormData>(key: K, val: RhythmFormData[K]) =>
    setForm((f) => ({ ...f, [key]: val }));

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(44,26,14,0.28)",
              zIndex: 45,
            }}
          />

          {/* Panel */}
          <motion.aside
            key="panel"
            initial={{ x: 360, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 360, opacity: 0 }}
            transition={{ type: "spring", stiffness: 280, damping: 28 }}
            style={{
              position: "fixed",
              top: 0,
              right: 0,
              bottom: 0,
              width: 360,
              background: "var(--bg)",
              borderLeft: "1px solid var(--border)",
              zIndex: 50,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              padding: "28px 24px",
              gap: 22,
            }}
          >
            {/* Header */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <h2
                className="font-display"
                style={{ fontSize: 20, fontWeight: 400, color: "var(--text)" }}
              >
                {isEdit ? "Edit rhythm" : "Add rhythm"}
              </h2>
              <button
                onClick={onClose}
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 7,
                  border: "none",
                  background: "transparent",
                  color: "var(--text-muted)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <X size={16} />
              </button>
            </div>

            {/* Form */}
            <form
              onSubmit={handleSubmit}
              style={{ display: "flex", flexDirection: "column", gap: 20, flex: 1 }}
            >
              {/* Name */}
              <div>
                <label style={LABEL}>Name</label>
                <input
                  style={INPUT}
                  type="text"
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="e.g. Morning run"
                  maxLength={80}
                  required
                  autoFocus
                />
              </div>

              {/* Scheduling hint */}
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                  <label style={{ ...LABEL, marginBottom: 0 }}>
                    Scheduling hint{" "}
                    <span style={{ color: "var(--text-faint)", textTransform: "none" as const, letterSpacing: 0 }}>
                      (optional)
                    </span>
                  </label>
                  <FieldTooltip content="Helps the app pick the right slot. Most useful: when it fits best ('mornings only') and what it leads into ('before deep work')." />
                </div>
                <textarea
                  style={{
                    ...INPUT,
                    resize: "none" as const,
                    minHeight: 62,
                    lineHeight: 1.5,
                  }}
                  value={form.description}
                  onChange={(e) => set("description", e.target.value)}
                  placeholder="e.g. Best in the morning, before deep work"
                  maxLength={80}
                />
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--text-faint)",
                    textAlign: "right" as const,
                    marginTop: 3,
                  }}
                >
                  {form.description.length} / 80
                </div>
              </div>

              {/* Sessions per week */}
              <div>
                <label style={LABEL}>Sessions per week</label>
                <Stepper
                  value={form.sessions_per_week}
                  min={1}
                  max={7}
                  onChange={(v) => set("sessions_per_week", v)}
                />
              </div>

              {/* Duration — 15-min increments */}
              <div>
                <label style={LABEL}>
                  Session duration{" "}
                  <span style={{ color: "var(--text-faint)", textTransform: "none", letterSpacing: 0 }}>
                    (minutes)
                  </span>
                </label>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto 1fr",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <select
                    style={INPUT}
                    value={form.session_min}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      set("session_min", v);
                      if (v > form.session_max) set("session_max", v);
                    }}
                  >
                    {DURATION_OPTIONS.map((m) => (
                      <option key={m} value={m}>{m} min</option>
                    ))}
                  </select>
                  <span style={{ fontSize: 11, color: "var(--text-faint)", textAlign: "center" }}>
                    to
                  </span>
                  <select
                    style={INPUT}
                    value={form.session_max}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      set("session_max", v);
                      if (v < form.session_min) set("session_min", v);
                    }}
                  >
                    {DURATION_OPTIONS.map((m) => (
                      <option key={m} value={m}>{m} min</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Days of week */}
              <div>
                <label style={LABEL}>Days</label>

                {/* "Any day" toggle. When on, all 7 days are selected and the
                    chip picker is hidden. When off, user picks specific days
                    from the chips below. Toggling off from "any" pre-selects
                    weekdays (Mon-Fri) — most common starting subset, user
                    can adjust from there. */}
                {(() => {
                  const isAnyDay = form.days_of_week.length === 7;
                  const setAnyDay = (on: boolean) => {
                    if (on) {
                      set("days_of_week", ALL_DAYS.map((d) => d.key));
                    } else if (isAnyDay) {
                      // Toggling OFF from all-7 → start from weekdays
                      set("days_of_week", ["monday", "tuesday", "wednesday", "thursday", "friday"]);
                    }
                    // else: already a partial selection, leave untouched
                  };
                  return (
                    <>
                      <button
                        type="button"
                        onClick={() => setAnyDay(!isAnyDay)}
                        aria-pressed={isAnyDay}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          padding: "6px 10px",
                          borderRadius: 8,
                          border: `1px solid ${isAnyDay ? "var(--accent)" : "var(--border)"}`,
                          background: isAnyDay ? "var(--accent-tint)" : "var(--surface-raised)",
                          color: isAnyDay ? "var(--accent)" : "var(--text-muted)",
                          fontSize: 12,
                          fontFamily: "var(--font-literata)",
                          cursor: "pointer",
                          transition: "all 0.12s",
                          marginBottom: isAnyDay ? 6 : 8,
                        }}
                      >
                        <span
                          aria-hidden="true"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            width: 14,
                            height: 14,
                            borderRadius: 4,
                            border: `1px solid ${isAnyDay ? "var(--accent)" : "var(--border-strong, var(--border))"}`,
                            background: isAnyDay ? "var(--accent)" : "transparent",
                            color: "var(--bg)",
                            fontSize: 11,
                            lineHeight: 1,
                          }}
                        >
                          {isAnyDay ? "✓" : ""}
                        </span>
                        <span style={{ fontWeight: isAnyDay ? 600 : 400 }}>Any day</span>
                      </button>

                      {!isAnyDay && (
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {ALL_DAYS.map((d) => {
                            const on = form.days_of_week.includes(d.key);
                            return (
                              <button
                                key={d.key}
                                type="button"
                                onClick={() => {
                                  const next = on
                                    ? form.days_of_week.filter((k) => k !== d.key)
                                    : [...form.days_of_week, d.key];
                                  // Sort by canonical Mon→Sun order so the array stays predictable.
                                  next.sort((a, b) =>
                                    ALL_DAYS.findIndex((x) => x.key === a) -
                                    ALL_DAYS.findIndex((x) => x.key === b)
                                  );
                                  set("days_of_week", next);
                                }}
                                aria-pressed={on}
                                aria-label={d.key}
                                style={{
                                  width: 36,
                                  height: 36,
                                  borderRadius: 8,
                                  border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                                  background: on ? "var(--accent-tint)" : "var(--surface-raised)",
                                  color: on ? "var(--accent)" : "var(--text-muted)",
                                  fontSize: 12,
                                  fontWeight: on ? 600 : 400,
                                  fontFamily: "var(--font-literata)",
                                  cursor: "pointer",
                                  transition: "all 0.12s",
                                }}
                              >
                                {d.short}
                                <span style={{ position: "absolute", left: -9999 }}>
                                  {/* full name for screen readers */}{d.key}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </>
                  );
                })()}

                <p style={{ fontSize: 11, color: "var(--text-faint)", fontStyle: "italic", marginTop: 6 }}>
                  {form.days_of_week.length === 7
                    ? "Papyrus can place this rhythm on any day."
                    : "Papyrus will only place this rhythm on the selected days."}
                </p>
              </div>

              {/* End date */}
              <div>
                <label style={LABEL}>
                  End date{" "}
                  <span style={{ color: "var(--text-faint)", textTransform: "none", letterSpacing: 0 }}>
                    (optional)
                  </span>
                </label>
                <input
                  style={INPUT}
                  type="date"
                  value={form.end_date}
                  onChange={(e) => set("end_date", e.target.value)}
                />
              </div>

              {/* Error */}
              {error && (
                <p style={{ fontSize: 12, color: "var(--danger)", fontStyle: "italic" }}>
                  {error}
                </p>
              )}

              {/* Submit */}
              <button
                type="submit"
                disabled={saving || !form.name.trim()}
                style={{
                  marginTop: "auto",
                  padding: "11px 20px",
                  background: "var(--accent)",
                  color: "#fff",
                  border: "none",
                  borderRadius: 9,
                  fontFamily: "var(--font-literata)",
                  fontSize: 13,
                  cursor: saving || !form.name.trim() ? "not-allowed" : "pointer",
                  opacity: saving || !form.name.trim() ? 0.55 : 1,
                  transition: "opacity 0.15s",
                }}
              >
                {saving ? "Saving…" : isEdit ? "Save changes" : "Add rhythm"}
              </button>
            </form>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
