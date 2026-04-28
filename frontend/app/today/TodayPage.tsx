"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiFetch } from "@/utils/api";
import NudgeBanner, { type SetupNudge } from "@/components/NudgeBanner";
import DayColumn from "./DayColumn";
import TodaySkeleton from "./TodaySkeleton";
import ResearchSnippet from "./ResearchSnippet";
import ReviewPill from "./ReviewPill";
import ReviewModal from "./ReviewModal";
import SplitPlanButton from "./SplitPlanButton";
import PlanningPanel from "./PlanningPanel";
import ReplanButton from "./ReplanButton";
import ReplanModal from "./ReplanModal";

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
  review_queue: { has_unreviewed: boolean; count: number; dates: string[] };
  setup_nudge: SetupNudge | null;
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
  const [replanOpen, setReplanOpen] = useState(false);
  const [setupNudge, setSetupNudge] = useState<SetupNudge | null>(null);

  const [planningOpen, setPlanningOpen] = useState(false);
  const [planningContext, setPlanningContext] = useState<string | undefined>();
  const [planningTarget, setPlanningTarget] = useState<"today" | "tomorrow">("today");
  const [planningStatus, setPlanningStatus] = useState<"idle" | "working" | "proposal">("idle");
  const [proposedSchedule, setProposedSchedule] = useState<ScheduledItem[] | null>(null);
  // True when the planner short-circuited because we're past today's effective
  // cutoff. Drives the "Plan tomorrow" CTA banner above the day columns.
  const [autoShiftToTomorrowSuggested, setAutoShiftToTomorrowSuggested] = useState(false);

  const windowWidth = useWindowWidth();

  // When the user opens Plan with a target day, focus the schedule view on
  // that day. Without this, planningTarget="tomorrow" leaves today's column
  // pinned in the foreground and the user has to manually navigate to see
  // the proposed schedule.
  const focusedDay: "today" | "tomorrow" =
    planningOpen && planningTarget === "tomorrow" ? "tomorrow" : "today";

  useEffect(() => {
    if (planningOpen) setActiveTab(planningTarget);
  }, [planningOpen, planningTarget]);

  const load = useCallback(async () => {
    const { data: session } = await supabase.auth.getSession();
    const tok = session.session?.access_token ?? "";
    setToken(tok);
    try {
      const result = await apiFetch<TodayResponse>("/api/today", tok);
      setData(result);
      setSetupNudge(result.setup_nudge ?? null);
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
  // LOCAL date as YYYY-MM-DD. toISOString() returns UTC which is off-by-one
  // for users in negative offsets after the local evening — that mismatch was
  // pushing every proposed task block 24h off-screen.
  const localDateIso = (offsetDays: number = 0): string => {
    const d = new Date();
    d.setDate(d.getDate() + offsetDays);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  const todayColumnData: DayData | null =
    planningStatus === "proposal" && proposedSchedule && planningTarget === "today"
      ? {
          ...(data?.today ?? {
            schedule_date: localDateIso(0),
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
            schedule_date: localDateIso(1),
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

  // Replan is mid-day recovery: only available after noon and only when today is confirmed.
  const nowDate = new Date();
  const showReplan = isConfirmed && nowDate.getHours() >= 12;

  // Afternoon tasks (for the Replan triage modal): today's scheduled items starting from now.
  const afternoonTasks: ScheduledItem[] = (data?.today?.scheduled ?? []).filter((item) => {
    return new Date(item.start_time) >= nowDate;
  });

  const handlePlan = (contextNote?: string, target: "today" | "tomorrow" = "today") => {
    setPlanningContext(contextNote);
    setPlanningTarget(target);
    setPlanningOpen(true);
    setPlanningStatus("working");
    setProposedSchedule(null);
    setAutoShiftToTomorrowSuggested(false);
  };

  const handlePanelClose = () => {
    setPlanningOpen(false);
    setPlanningStatus("idle");
    setProposedSchedule(null);
    setPlanningContext(undefined);
    setPlanningTarget("today");
    setAutoShiftToTomorrowSuggested(false);
  };

  const handlePanelConfirm = () => {
    setPlanningOpen(false);
    setPlanningStatus("idle");
    setProposedSchedule(null);
    setPlanningContext(undefined);
    setPlanningTarget("today");
    setAutoShiftToTomorrowSuggested(false);
    setLoading(true);
    load();
  };

  const handleScheduleProposed = (schedule: ScheduledItem[], autoShift: boolean) => {
    setProposedSchedule(schedule);
    setAutoShiftToTomorrowSuggested(autoShift);
    setPlanningStatus("proposal");
  };

  // Backend signals the empty-state via auto_shift_to_tomorrow_suggested when
  // "Plan today" is invoked past the user's effective cutoff (e.g. 11:30 PM
  // with a 23:00 cutoff). The reasoning_summary in the planning panel already
  // explains why; this surfaces a one-click "Plan tomorrow" CTA so the user
  // doesn't have to close the panel and re-pick the target date.
  const showPlanTomorrowCta =
    planningStatus === "proposal"
    && autoShiftToTomorrowSuggested
    && planningTarget === "today";

  const handlePlanTomorrowFromCta = () => {
    handlePanelClose();
    handlePlan(undefined, "tomorrow");
  };

  return (
    <div style={{ display: "flex", height: "100dvh", overflow: "hidden" }}>
      {/* Main today content */}
      <div className="app-main-pad" style={{ flex: 1, overflowY: "auto" }}>
        <NudgeBanner nudge={setupNudge} />
        {showPlanTomorrowCta && (
          <div
            style={{
              margin: "0 0 12px",
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--accent-tint)",
              border: "1px solid rgba(196,130,26,0.18)",
              display: "flex",
              gap: 10,
              alignItems: "center",
              flexWrap: "wrap",
              justifyContent: "space-between",
            }}
            role="status"
          >
            <span
              style={{
                fontSize: 13,
                color: "var(--text)",
                fontFamily: "var(--font-literata)",
                fontStyle: "italic",
                lineHeight: 1.4,
              }}
            >
              No meaningful time left to plan today. Plan tomorrow instead?
            </span>
            <button
              type="button"
              onClick={handlePlanTomorrowFromCta}
              style={{
                padding: "6px 12px",
                background: "var(--accent)",
                color: "var(--bg)",
                border: "none",
                borderRadius: 8,
                fontSize: 12,
                fontFamily: "var(--font-literata)",
                cursor: "pointer",
                letterSpacing: "0.01em",
                minHeight: 32,
              }}
            >
              Plan tomorrow →
            </button>
          </div>
        )}
        {/* Header */}
        <motion.div
          initial="hidden" animate="show" custom={0} variants={FADE}
          className="today-header-row"
        >
          <div>
            <h1
              className="font-display"
              style={{ fontSize: "clamp(24px, 6vw, 32px)", letterSpacing: "-0.02em", color: "var(--text)", marginBottom: 4 }}
            >
              Schedule
            </h1>
            <p style={{ color: "var(--text-muted)", fontSize: 13, fontFamily: "var(--font-literata)" }}>
              Yesterday, today, and what&apos;s ahead.
            </p>
          </div>
          <div className="today-header-actions">
            {data?.review_queue?.has_unreviewed && (
              <ReviewPill onClick={() => setReviewOpen(true)} />
            )}
            {showReplan && (
              <ReplanButton onClick={() => setReplanOpen(true)} />
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
            {!planningOpen && focusedDay === "today" && (
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

          {/* Primary column: switches to tomorrow when planningTarget is tomorrow.
              This is a SWITCH, not an expand — today is hidden alongside, so the
              user lands on the day they're actually planning. */}
          <AnimatePresence initial={false} mode="wait">
            {focusedDay === "today" ? (
              <motion.div
                key="primary-today"
                layout
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                style={{ flex: 1 }}
              >
                <DayColumn label="Today" dayData={todayColumnData} isToday={true} planningStatus={planningStatus} />
              </motion.div>
            ) : (
              <motion.div
                key="primary-tomorrow"
                layout
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                style={{ flex: 1 }}
              >
                <DayColumn label="Tomorrow" dayData={tomorrowColumnData} isToday={false} planningStatus={planningStatus} />
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence initial={false}>
            {focusedDay === "today" && (!planningOpen || windowWidth >= 1100) && (
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
                className="today-mobile-tab"
                style={{
                  flex: 1,
                  background: "none",
                  border: "none",
                  borderBottom: activeTab === d.key ? "2px solid var(--accent)" : "2px solid transparent",
                  color: activeTab === d.key ? "var(--accent)" : "var(--text-muted)",
                  fontSize: 14,
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
              dayData={
                activeTab === "today"
                  ? todayColumnData
                  : activeTab === "tomorrow"
                  ? tomorrowColumnData
                  : data?.yesterday ?? null
              }
              isToday={activeTab === "today"}
              planningStatus={
                (activeTab === "today" && planningTarget === "today") ||
                (activeTab === "tomorrow" && planningTarget === "tomorrow")
                  ? planningStatus
                  : undefined
              }
            />
          </div>
        </div>

        <ResearchSnippet />

        {/* Review modal */}
        {reviewOpen && (
          <ReviewModal
            token={token}
            dates={data?.review_queue?.dates ?? []}
            onClose={() => setReviewOpen(false)}
          />
        )}

        {/* Replan modal — mid-day afternoon recovery */}
        {replanOpen && (
          <ReplanModal
            afternoonTasks={afternoonTasks}
            token={token}
            onClose={() => setReplanOpen(false)}
            onConfirm={() => {
              setReplanOpen(false);
              setLoading(true);
              load();
            }}
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


