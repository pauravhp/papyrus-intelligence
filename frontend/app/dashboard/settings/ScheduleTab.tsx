// frontend/app/dashboard/settings/ScheduleTab.tsx
"use client";

import { useState } from "react";
import { apiPost } from "@/utils/api";

interface ScheduleTabProps {
  config: Record<string, unknown>;
  getToken: () => Promise<string>;
}

const INPUT: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 8,
  padding: "8px 11px",
  fontSize: 13,
  fontFamily: "var(--font-literata)",
  outline: "none",
  width: "100%",
  transition: "border-color 0.15s",
  WebkitAppearance: "none",
};

const LABEL: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--text-muted)",
  marginBottom: 5,
};

const GROUP_LABEL: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: "var(--text-faint)",
  paddingBottom: 10,
  marginBottom: 16,
  borderBottom: "1px solid var(--border)",
};

function Field({
  label,
  value,
  onChange,
  type = "text",
  style,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={LABEL}>{label}</label>
      <input
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        style={{ ...INPUT, ...style }}
      />
    </div>
  );
}

export default function ScheduleTab({ config, getToken }: ScheduleTabProps) {
  const initSleep = (config.sleep ?? {}) as Record<string, unknown>;
  const initScheduling = (config.scheduling ?? {}) as Record<string, unknown>;
  const initDailyBlocks = (config.daily_blocks as Array<Record<string, unknown>>) ?? [];
  const lunchBlock  = initDailyBlocks.find(b => String(b.name).toLowerCase() === "lunch");
  const dinnerBlock = initDailyBlocks.find(b => String(b.name).toLowerCase() === "dinner");

  const [sleep, setSleepField] = useState({
    default_wake_time:       (initSleep.default_wake_time as string)        ?? "09:00",
    morning_buffer_minutes:  (initSleep.morning_buffer_minutes as number)   ?? 90,
    first_task_not_before:   (initSleep.first_task_not_before as string)    ?? "10:30",
    no_tasks_after:          (initSleep.no_tasks_after as string)           ?? "23:30",
    weekend_days:            (initSleep.weekend_days as string[])           ?? ["saturday", "sunday"],
    weekend_nothing_before:  (initSleep.weekend_nothing_before as string)   ?? "13:00",
  });

  const [scheduling, setSchedulingField] = useState({
    min_gap_between_tasks_minutes: (initScheduling.min_gap_between_tasks_minutes as number) ?? 10,
    max_tasks_per_day:             (initScheduling.max_tasks_per_day as number)             ?? 10,
  });

  const [meals, setMealsField] = useState({
    lunch_start:  (lunchBlock?.start  as string) ?? "12:30",
    lunch_end:    (lunchBlock?.end    as string) ?? "13:30",
    dinner_start: (dinnerBlock?.start as string) ?? "19:00",
    dinner_end:   (dinnerBlock?.end   as string) ?? "20:00",
  });

  const setMeal = (key: string, value: string) =>
    setMealsField(prev => ({ ...prev, [key]: value }));

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const setSleep = (key: string, value: string | number | string[]) =>
    setSleepField((prev) => ({ ...prev, [key]: value }));

  const toggleWeekendDay = (day: string) => {
    setSleepField((prev) => {
      const has = prev.weekend_days.includes(day);
      const next = has
        ? prev.weekend_days.filter((d) => d !== day)
        : [...prev.weekend_days, day];
      return { ...prev, weekend_days: next };
    });
  };

  const setScheduling = (key: string, value: number) =>
    setSchedulingField((prev) => ({ ...prev, [key]: value }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const token = await getToken();
      const otherBlocks = initDailyBlocks.filter(
        b => !["lunch", "dinner"].includes(String(b.name).toLowerCase())
      );
      const updated = {
        ...config,
        sleep: { ...((config.sleep as object) ?? {}), ...sleep },
        scheduling: { ...((config.scheduling as object) ?? {}), ...scheduling },
        daily_blocks: [
          ...otherBlocks,
          { name: "Lunch",  start: meals.lunch_start,  end: meals.lunch_end,  days: "all", movable: false, buffer_before_minutes: 0, buffer_after_minutes: 0 },
          { name: "Dinner", start: meals.dinner_start, end: meals.dinner_end, days: "all", movable: false, buffer_before_minutes: 0, buffer_after_minutes: 0 },
        ],
      };
      await apiPost("/api/onboard/promote", { config: updated }, token);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      {/* Morning */}
      <div style={{ marginBottom: 32 }}>
        <p style={GROUP_LABEL}>Morning</p>
        <Field
          label="Wake time"
          type="time"
          value={sleep.default_wake_time}
          onChange={(v) => setSleep("default_wake_time", v)}
          style={{ maxWidth: 160 }}
        />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field
            label="Morning buffer (min)"
            type="number"
            value={sleep.morning_buffer_minutes}
            onChange={(v) => setSleep("morning_buffer_minutes", parseInt(v, 10) || 0)}
          />
          <Field
            label="First task not before"
            type="time"
            value={sleep.first_task_not_before}
            onChange={(v) => setSleep("first_task_not_before", v)}
          />
        </div>
      </div>

      {/* Evening */}
      <div style={{ marginBottom: 32 }}>
        <p style={GROUP_LABEL}>Evening</p>
        <Field
          label="No tasks after"
          type="time"
          value={sleep.no_tasks_after}
          onChange={(v) => setSleep("no_tasks_after", v)}
          style={{ maxWidth: 160 }}
        />
      </div>

      {/* Weekend */}
      <div style={{ marginBottom: 32 }}>
        <p style={GROUP_LABEL}>Weekend</p>
        <p style={{ fontSize: 12, color: "var(--text-faint)", fontFamily: "var(--font-literata)", fontStyle: "italic", marginBottom: 16, lineHeight: 1.65 }}>
          Pick the days you sleep in. Nothing is scheduled before the weekend start time on those days.
        </p>
        <label style={LABEL}>Weekend days</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
          {["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].map((day) => {
            const on = sleep.weekend_days.includes(day);
            return (
              <button
                key={day}
                type="button"
                onClick={() => toggleWeekendDay(day)}
                style={{
                  padding: "6px 12px",
                  borderRadius: 8,
                  border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                  background: on ? "var(--accent-tint)" : "transparent",
                  color: on ? "var(--accent)" : "var(--text-muted)",
                  fontSize: 12,
                  fontFamily: "var(--font-literata)",
                  cursor: "pointer",
                  textTransform: "capitalize",
                  transition: "all 0.12s",
                }}
              >
                {day.slice(0, 3)}
              </button>
            );
          })}
        </div>
        <Field
          label="Weekend starts at"
          type="time"
          value={sleep.weekend_nothing_before}
          onChange={(v) => setSleep("weekend_nothing_before", v)}
          style={{ maxWidth: 160 }}
        />
      </div>

      {/* Day limits */}
      <div style={{ marginBottom: 32 }}>
        <p style={GROUP_LABEL}>Day limits</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field
            label="Min gap between tasks (min)"
            type="number"
            value={scheduling.min_gap_between_tasks_minutes}
            onChange={(v) => setScheduling("min_gap_between_tasks_minutes", parseInt(v, 10) || 0)}
          />
          <Field
            label="Max tasks / day"
            type="number"
            value={scheduling.max_tasks_per_day}
            onChange={(v) => setScheduling("max_tasks_per_day", parseInt(v, 10) || 1)}
          />
        </div>
      </div>

      {/* Meals */}
      <div style={{ marginBottom: 32 }}>
        <p style={GROUP_LABEL}>Meals</p>
        <p style={{ fontSize: 12, color: "var(--text-faint)", fontFamily: "var(--font-literata)", fontStyle: "italic", marginBottom: 20, lineHeight: 1.65 }}>
          Papyrus keeps these free — no scheduling over lunch or dinner. Tell it once, never mention it again.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Lunch starts" type="time" value={meals.lunch_start}  onChange={v => setMeal("lunch_start",  v)} />
          <Field label="Lunch ends"   type="time" value={meals.lunch_end}    onChange={v => setMeal("lunch_end",    v)} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <Field label="Dinner starts" type="time" value={meals.dinner_start} onChange={v => setMeal("dinner_start", v)} />
          <Field label="Dinner ends"   type="time" value={meals.dinner_end}   onChange={v => setMeal("dinner_end",   v)} />
        </div>
      </div>

      {error && (
        <p style={{ color: "var(--danger)", fontSize: 12, marginBottom: 12 }}>{error}</p>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          padding: "10px 22px",
          background: saving ? "var(--accent-tint)" : "var(--accent)",
          color: saving ? "var(--accent)" : "var(--bg)",
          border: "none",
          borderRadius: 9,
          fontFamily: "var(--font-literata)",
          fontSize: 13,
          fontWeight: 500,
          cursor: saving ? "not-allowed" : "pointer",
          transition: "background 0.15s",
        }}
      >
        {saved ? "Saved" : saving ? "Saving…" : "Save schedule"}
      </button>
    </div>
  );
}
