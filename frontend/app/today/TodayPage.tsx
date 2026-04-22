"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiFetch } from "@/utils/api";
import NudgeBanner from "@/components/NudgeBanner";
import DayColumn from "./DayColumn";
import TodaySkeleton from "./TodaySkeleton";
import ResearchSnippet from "./ResearchSnippet";
import ReviewButton from "./ReviewButton";
import ReviewModal from "./ReviewModal";
import SplitPlanButton from "./SplitPlanButton";
import PlanningPanel from "./PlanningPanel";

function useWindowWidth(): number {
  const [width, setWidth] = useState(
    typeof window !== "undefined" ? window.innerWidth : 1280
  );
  useEffect(() => {
    const handler = () => setWidth(window.innerWidth);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);
  return width;
}

export interface ScheduledItem {
  task_id: string;
  task_name: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  category: "deep_work" | "admin" | null;
}

export interface PushedItem {
  task_id: string;
  reason: string;
}

export interface GCalEvent {
  id: string;
  summary: string;
  start_time: string;
  end_time: string;
  color_hex: string | null;  // from GCal event colorId mapped to hex
}

export interface DayData {
  schedule_date: string;
  scheduled: ScheduledItem[];
  pushed: PushedItem[];
  confirmed_at: string | null;
  gcal_events: GCalEvent[];
  all_day_events: string[];
}

interface TodayResponse {
  yesterday: DayData | null;
  today: DayData | null;
  tomorrow: DayData | null;
  review_available: boolean;
  show_calendar_nudge: boolean;
}

const FADE = {
  hidden: { opacity: 0, y: 12 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.06, type: "spring" as const, stiffness: 100, damping: 16 },
  }),
};

export default function TodayPage() {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;
  const [data, setData] = useState<TodayResponse | null>(null);
  const [token, setToken] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"yesterday" | "today" | "tomorrow">("today");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [showCalendarNudge, setShowCalendarNudge] = useState(false);

  const [planningOpen, setPlanningOpen] = useState(false);
  const [planningContext, setPlanningContext] = useState<string | undefined>();
  const [planningTarget, setPlanningTarget] = useState<"today" | "tomorrow">("today");
  const [planningStatus, setPlanningStatus] = useState<"idle" | "working" | "proposal">("idle");
  const [proposedSchedule, setProposedSchedule] = useState<ScheduledItem[] | null>(null);

  const windowWidth = useWindowWidth();

  const load = useCallback(async () => {
    const { data: session } = await supabase.auth.getSession();
    const tok = session.session?.access_token ?? "";
    setToken(tok);
    try {
      const result = await apiFetch<TodayResponse>("/api/today", tok);
      setData(result);
      setShowCalendarNudge(result.show_calendar_nudge ?? false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load schedule");
    } finally {
      setLoading(false);
    }
  }, [supabase]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <TodaySkeleton />;
  if (error) return (
    <div style={{ padding: "32px 48px", color: "var(--text-muted)", fontFamily: "var(--font-literata)", fontSize: 14 }}>
      Could not load schedule. {error}
    </div>
  );

  const days: Array<{ key: "yesterday" | "today" | "tomorrow"; label: string }> = [
    { key: "yesterday", label: "Yesterday" },
    { key: "today",     label: "Today" },
    { key: "tomorrow",  label: "Tomorrow" },
  ];

  // Determine what to show in the Today column:
  // - while working: show skeleton (handled inside DayColumn via planningStatus prop)
  // - while proposal: show proposed blocks
  // - confirmed/idle: show actual data from API
  const todayColumnData: DayData | null =
    planningStatus === "proposal" && proposedSchedule && planningTarget === "today"
      ? {
          ...(data?.today ?? {
            schedule_date: new Date().toISOString().split("T")[0],
            pushed: [],
            confirmed_at: null,
            gcal_events: data?.today?.gcal_events ?? [],
            all_day_events: data?.today?.all_day_events ?? [],
          }),
          scheduled: proposedSchedule,
        }
      : data?.today ?? null;

  const tomorrowColumnData: DayData | null =
    planningStatus === "proposal" && proposedSchedule && planningTarget === "tomorrow"
      ? {
          ...(data?.tomorrow ?? {
            schedule_date: (() => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().split("T")[0]; })(),
            pushed: [],
            confirmed_at: null,
            gcal_events: data?.tomorrow?.gcal_events ?? [],
            all_day_events: data?.tomorrow?.all_day_events ?? [],
          }),
          scheduled: proposedSchedule,
        }
      : data?.tomorrow ?? null;

  // Single source of truth: confirmed_at on today's DayData
  const isConfirmed = !!data?.today?.confirmed_at;

  const handlePlan = (contextNote?: string, target: "today" | "tomorrow" = "today") => {
    setPlanningContext(contextNote);
    setPlanningTarget(target);
    setPlanningOpen(true);
    setPlanningStatus("working");
    setProposedSchedule(null);
  };

  const handlePanelClose = () => {
    setPlanningOpen(false);
    setPlanningStatus("idle");
    setProposedSchedule(null);
    setPlanningContext(undefined);
    setPlanningTarget("today");
  };

  const handlePanelConfirm = () => {
    setPlanningOpen(false);
    setPlanningStatus("idle");
    setProposedSchedule(null);
    setPlanningContext(undefined);
    setPlanningTarget("today");
    setLoading(true);
    load();
  };

  const handleScheduleProposed = (schedule: ScheduledItem[]) => {
    setProposedSchedule(schedule);
    setPlanningStatus("proposal");
  };

  return (
    <div style={{ display: "flex", height: "100dvh", overflow: "hidden" }}>
      {/* Main today content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "32px 48px 48px" }}>
        <NudgeBanner show={showCalendarNudge} />
        {/* Header */}
        <motion.div
          initial="hidden" animate="show" custom={0} variants={FADE}
          style={{ marginBottom: 32, display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}
        >
          <div>
            <h1
              className="font-display"
              style={{ fontSize: 32, letterSpacing: "-0.02em", color: "var(--text)", marginBottom: 4 }}
            >
              Schedule
            </h1>
            <p style={{ color: "var(--text-muted)", fontSize: 13, fontFamily: "var(--font-literata)" }}>
              Yesterday, today, and what&apos;s ahead.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
            {data?.review_available && (
              <ReviewButton onClick={() => setReviewOpen(true)} />
            )}
            <SplitPlanButton
              confirmed={isConfirmed}
              disabled={planningOpen}
              onPlan={handlePlan}
            />
          </div>
        </motion.div>

        {/* Desktop: 3-column (animated) */}
        <motion.div
          layout
          className="today-desktop"
          style={{ display: "flex", gap: 24 }}
        >
          <AnimatePresence initial={false}>
            {!planningOpen && (
              <motion.div
                key="yesterday"
                layout
                initial={{ opacity: 0, x: -30 }}
                animate={{ opacity: 0.6, x: 0 }}
                exit={{ opacity: 0, x: -40 }}
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
                style={{ width: 220, flexShrink: 0 }}
              >
                <DayColumn label="Yesterday" dayData={data?.yesterday ?? null} isToday={false} />
              </motion.div>
            )}
          </AnimatePresence>

          <motion.div layout style={{ flex: 1 }}>
            <DayColumn label="Today" dayData={todayColumnData} isToday={true} planningStatus={planningStatus} />
          </motion.div>

          <AnimatePresence initial={false}>
            {(!planningOpen || windowWidth >= 1100) && (
              <motion.div
                key="tomorrow"
                layout
                initial={{ opacity: 0, x: 30 }}
                animate={{ opacity: planningOpen ? 0.65 : 0.75, x: 0 }}
                exit={{ opacity: 0, x: 40 }}
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
                style={{ width: planningOpen ? 172 : 220, flexShrink: 0 }}
              >
                <DayColumn label="Tomorrow" dayData={tomorrowColumnData} isToday={false} planningStatus={planningTarget === "tomorrow" ? planningStatus : undefined} />
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>

        {/* Mobile: tabs */}
        <div className="today-mobile">
          <div
            role="tablist"
            style={{ display: "flex", borderBottom: "1px solid var(--border)", marginBottom: 24 }}
          >
            {days.map((d) => (
              <button
                key={d.key}
                id={`tab-${d.key}`}
                role="tab"
                aria-selected={activeTab === d.key}
                aria-controls="today-tabpanel"
                onClick={() => setActiveTab(d.key)}
                style={{
                  flex: 1,
                  padding: "10px 0",
                  background: "none",
                  border: "none",
                  borderBottom: activeTab === d.key ? "2px solid var(--accent)" : "2px solid transparent",
                  color: activeTab === d.key ? "var(--accent)" : "var(--text-muted)",
                  fontSize: 13,
                  fontFamily: "var(--font-literata)",
                  cursor: "pointer",
                  marginBottom: -1,
                }}
              >
                {d.label}
              </button>
            ))}
          </div>
          <div
            id="today-tabpanel"
            role="tabpanel"
            aria-labelledby={`tab-${activeTab}`}
          >
            <DayColumn
              label={days.find(d => d.key === activeTab)!.label}
              dayData={data?.[activeTab] ?? null}
              isToday={activeTab === "today"}
            />
          </div>
        </div>

        <ResearchSnippet />

        {/* Review modal */}
        {reviewOpen && (
          <ReviewModal
            token={token}
            onClose={() => setReviewOpen(false)}
          />
        )}
      </div>

      {/* Planning panel — slides in when open */}
      <AnimatePresence>
        {planningOpen && (
          <motion.div
            key="planning-panel"
            initial={{ x: 340, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 340, opacity: 0 }}
            transition={{ type: "spring", stiffness: 280, damping: 28 }}
            style={{ flexShrink: 0 }}
          >
            <PlanningPanel
              token={token}
              contextNote={planningContext}
              targetDate={planningTarget}
              onScheduleProposed={handleScheduleProposed}
              onConfirm={handlePanelConfirm}
              onClose={handlePanelClose}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}


