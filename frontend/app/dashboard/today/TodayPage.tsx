"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import { apiFetch } from "@/utils/api";
import DayColumn from "./DayColumn";
import TodaySkeleton from "./TodaySkeleton";
import ResearchSnippet from "./ResearchSnippet";
import ReplanButton from "./ReplanButton";
import ReplanModal from "./ReplanModal";
import ReviewButton from "./ReviewButton";
import ReviewModal from "./ReviewModal";

export interface ScheduledItem {
  task_id: string;
  task_name: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
}

export interface PushedItem {
  task_id: string;
  reason: string;
}

export interface DayData {
  schedule_date: string;
  scheduled: ScheduledItem[];
  pushed: PushedItem[];
  confirmed_at: string | null;
}

interface TodayResponse {
  yesterday: DayData | null;
  today: DayData | null;
  tomorrow: DayData | null;
  review_available: boolean;
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
  const [modalOpen, setModalOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);

  const load = useCallback(async () => {
    const { data: session } = await supabase.auth.getSession();
    const tok = session.session?.access_token ?? "";
    setToken(tok);
    try {
      const result = await apiFetch<TodayResponse>("/api/today", tok);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load schedule");
    } finally {
      setLoading(false);
    }
  }, [supabase]);

  useEffect(() => { load(); }, [load]);

  const now = new Date();
  const isPastNoon = now.getHours() >= 12;
  const showReplanButton = isPastNoon && !!data?.today;

  // Afternoon tasks: start_time >= now
  const afternoonTasks: ScheduledItem[] = (data?.today?.scheduled ?? []).filter((item) => {
    return new Date(item.start_time) >= now;
  });

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

  return (
    <div style={{ padding: "32px 48px 48px" }}>
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
        {showReplanButton && (
          <ReplanButton onClick={() => setModalOpen(true)} />
        )}
        {data?.review_available && (
          <ReviewButton onClick={() => setReviewOpen(true)} />
        )}
      </motion.div>

      {/* Desktop: 3-column */}
      <div
        className="today-desktop"
        style={{ display: "flex", gap: 24 }}
      >
        <motion.div custom={0} variants={FADE} initial="hidden" animate="show"
          style={{ width: 220, opacity: 0.6, flexShrink: 0 }}>
          <DayColumn label="Yesterday" dayData={data?.yesterday ?? null} isToday={false} />
        </motion.div>

        <motion.div custom={1} variants={FADE} initial="hidden" animate="show"
          style={{ flex: 1 }}>
          <DayColumn label="Today" dayData={data?.today ?? null} isToday={true} />
        </motion.div>

        <motion.div custom={2} variants={FADE} initial="hidden" animate="show"
          style={{ width: 220, opacity: 0.8, flexShrink: 0 }}>
          <DayColumn label="Tomorrow" dayData={data?.tomorrow ?? null} isToday={false} />
        </motion.div>
      </div>

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

      {/* Replan modal */}
      {modalOpen && (
        <ReplanModal
          afternoonTasks={afternoonTasks}
          token={token}
          onClose={() => setModalOpen(false)}
          onConfirm={() => {
            setModalOpen(false);
            setLoading(true);
            load();
          }}
        />
      )}

      {/* Review modal */}
      {reviewOpen && (
        <ReviewModal
          token={token}
          onClose={() => setReviewOpen(false)}
        />
      )}
    </div>
  );
}

