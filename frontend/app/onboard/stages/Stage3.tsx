"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiPost } from "@/utils/api";
import StepDots from "@/components/StepDots";

// ── Types ─────────────────────────────────────────────────────────────────────

interface FreeWindow {
  start: string;
  end: string;
  duration_minutes: number;
  block_type: string;
}

interface CalEvent {
  summary: string;
  start: string;
  end: string;
  color_id: string | null;
  is_all_day: boolean;
}

interface Stage3Data {
  free_windows: FreeWindow[];
  events_consuming_time: CalEvent[];
  effective_wake: string | null;
  first_task_not_before: string | null;
}

interface Stage3Props {
  onAdvance: () => void;
}

// ── Timeline constants ────────────────────────────────────────────────────────

const DAY_START_H = 8;    // 8am
const DAY_END_H = 24;     // midnight
const TOTAL_HOURS = DAY_END_H - DAY_START_H; // 16
const PX_PER_HOUR = 30;
const TIMELINE_H = TOTAL_HOURS * PX_PER_HOUR; // 480px

function timeToY(iso: string): number {
  const d = new Date(iso);
  const hours = d.getHours() + d.getMinutes() / 60;
  const clamped = Math.min(Math.max(hours, DAY_START_H), DAY_END_H);
  return (clamped - DAY_START_H) * PX_PER_HOUR;
}

function durationPx(startIso: string, endIso: string): number {
  const startMs = new Date(startIso).getTime();
  const endMs = new Date(endIso).getTime();
  const mins = (endMs - startMs) / 60000;
  return Math.max((mins / 60) * PX_PER_HOUR, 4);
}

// ── Hour labels ───────────────────────────────────────────────────────────────

function HourLabels() {
  const hours = Array.from({ length: TOTAL_HOURS + 1 }, (_, i) => DAY_START_H + i);
  return (
    <>
      {hours.map((h) => (
        <div
          key={h}
          className="absolute left-0 text-right pr-2 select-none"
          style={{
            top: (h - DAY_START_H) * PX_PER_HOUR - 8,
            width: 44,
            fontSize: 10,
            color: "#475569",
            lineHeight: 1,
          }}
        >
          {h === 24 ? "12am" : h === 12 ? "12pm" : h > 12 ? `${h - 12}pm` : `${h}am`}
        </div>
      ))}
    </>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Stage3({ onAdvance }: Stage3Props) {
  const supabase = createClient();
  const [data, setData] = useState<Stage3Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [promoting, setPromoting] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const calledRef = useRef(false);

  useEffect(() => {
    if (calledRef.current) return;
    calledRef.current = true;

    (async () => {
      try {
        const { data: sessionData } = await supabase.auth.getSession();
        const token = sessionData.session?.access_token;
        if (!token) throw new Error("Not authenticated");

        const creds = JSON.parse(sessionStorage.getItem("sfm_creds") ?? "{}");
        const stage2 = JSON.parse(sessionStorage.getItem("sfm_stage2") ?? "{}");
        const draftConfig = stage2.updated_config ?? {};

        const result = await apiPost<Stage3Data>(
          "/api/onboard/stage3",
          {
            draft_config: draftConfig,
            timezone: creds.timezone ?? "UTC",
            calendar_ids: creds.calendar_ids ?? [],
          },
          token,
        );
        setData(result);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handlePromote = async () => {
    setPromoting(true);
    setError(null);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      if (!token) throw new Error("Not authenticated");

      const stage2 = JSON.parse(sessionStorage.getItem("sfm_stage2") ?? "{}");
      const draftConfig = stage2.updated_config ?? {};
      const creds = JSON.parse(sessionStorage.getItem("sfm_creds") ?? "{}");

      await apiPost("/api/onboard/promote", {
        draft_config: draftConfig,
        groq_api_key: creds.groq_api_key ?? "",
        anthropic_api_key: creds.anthropic_api_key ?? "",
        todoist_api_key: creds.todoist_api_key ?? "",
      }, token);
      onAdvance();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPromoting(false);
    }
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-start px-4 py-16"
      style={{ background: "#080810" }}
    >
      <StepDots current={3} />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 90, damping: 14 }}
        className="mt-8 w-full max-w-sm"
      >
        <h1
          className="font-display text-center text-white mb-1"
          style={{ fontSize: "clamp(1.5rem, 4vw, 2rem)", letterSpacing: "-0.025em" }}
        >
          Your day at a glance
        </h1>
        <p className="text-center text-sm mb-6" style={{ color: "#94a3b8" }}>
          Here's how your schedule looks with these settings.
        </p>

        {/* Timeline */}
        <div
          className="relative rounded-2xl overflow-hidden p-4"
          style={{
            background: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(255,255,255,0.07)",
          }}
        >
          {loading && (
            <div className="flex items-center justify-center" style={{ height: TIMELINE_H }}>
              <p className="text-sm" style={{ color: "#475569" }}>
                Building your schedule…
              </p>
            </div>
          )}

          {!loading && (
            <div
              className="relative ml-12"
              style={{ height: TIMELINE_H }}
            >
              {/* Hour labels */}
              <div className="absolute" style={{ left: -48, top: 0, height: TIMELINE_H }}>
                <HourLabels />
              </div>

              {/* Grid lines */}
              {Array.from({ length: TOTAL_HOURS + 1 }).map((_, i) => (
                <div
                  key={i}
                  className="absolute left-0 right-0"
                  style={{
                    top: i * PX_PER_HOUR,
                    borderTop: "1px solid rgba(255,255,255,0.05)",
                  }}
                />
              ))}

              {/* Free window bars */}
              {(data?.free_windows ?? []).map((w, i) => {
                const top = timeToY(w.start);
                const height = durationPx(w.start, w.end);
                return (
                  <motion.div
                    key={`fw-${i}`}
                    initial={{ scaleY: 0, opacity: 0 }}
                    animate={{ scaleY: 1, opacity: 1 }}
                    transition={{ delay: i * 0.06, type: "spring", stiffness: 120, damping: 16 }}
                    style={{
                      position: "absolute",
                      top,
                      left: 0,
                      right: 0,
                      height: Math.max(height, 4),
                      transformOrigin: "top",
                      background: "rgba(99,102,241,0.25)",
                      border: "1px solid rgba(99,102,241,0.5)",
                      borderRadius: 4,
                      boxShadow: "0 0 8px rgba(99,102,241,0.2)",
                    }}
                  >
                    {height >= 20 && (
                      <span
                        className="absolute left-2 leading-none"
                        style={{ fontSize: 9, color: "#818cf8", top: 4 }}
                      >
                        Free
                      </span>
                    )}
                  </motion.div>
                );
              })}

              {/* Event bars */}
              {(data?.events_consuming_time ?? []).map((ev, i) => {
                const top = timeToY(ev.start);
                const height = durationPx(ev.start, ev.end);
                return (
                  <motion.div
                    key={`ev-${i}`}
                    initial={{ scaleY: 0, opacity: 0 }}
                    animate={{ scaleY: 1, opacity: 1 }}
                    transition={{ delay: 0.3 + i * 0.06, type: "spring", stiffness: 120, damping: 16 }}
                    style={{
                      position: "absolute",
                      top,
                      left: 0,
                      right: 0,
                      height: Math.max(height, 6),
                      transformOrigin: "top",
                      background: "rgba(139,92,246,0.3)",
                      border: "1px solid rgba(139,92,246,0.55)",
                      borderRadius: 4,
                    }}
                  >
                    {height >= 18 && (
                      <span
                        className="absolute left-2 leading-none truncate"
                        style={{ fontSize: 9, color: "#c4b5fd", top: 4, maxWidth: "90%" }}
                      >
                        {ev.summary}
                      </span>
                    )}
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>

        {/* Legend */}
        {!loading && (
          <div className="flex gap-4 justify-center mt-3 mb-6">
            <div className="flex items-center gap-1.5">
              <div
                className="w-3 h-3 rounded-sm"
                style={{ background: "rgba(99,102,241,0.5)", border: "1px solid rgba(99,102,241,0.7)" }}
              />
              <span className="text-xs" style={{ color: "#64748b" }}>Free windows</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div
                className="w-3 h-3 rounded-sm"
                style={{ background: "rgba(139,92,246,0.5)", border: "1px solid rgba(139,92,246,0.7)" }}
              />
              <span className="text-xs" style={{ color: "#64748b" }}>Calendar events</span>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <p className="text-xs text-center mb-4" style={{ color: "#f43f5e" }}>
            {error}
          </p>
        )}

        {/* CTAs */}
        {!loading && (
          <div className="space-y-3">
            <button
              onClick={handlePromote}
              disabled={promoting}
              className="w-full py-3 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-50"
              style={{
                background: "#6366f1",
                boxShadow: "0 0 20px rgba(99,102,241,0.35)",
              }}
            >
              {promoting ? "Saving settings…" : "Looks good →"}
            </button>

            <button
              onClick={() => setShowHelp((v) => !v)}
              className="w-full text-xs transition-colors"
              style={{ color: "#475569" }}
            >
              Something looks off
            </button>

            {showHelp && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-xs text-center"
                style={{ color: "#64748b" }}
              >
                You can always adjust your schedule settings in the dashboard
                after onboarding.
              </motion.p>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}
