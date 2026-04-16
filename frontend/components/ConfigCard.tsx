"use client";

import { useState } from "react";
import ColorRuleCard from "@/components/ColorRuleCard";
import {
  ColorRule,
  calendarRulesToCategories,
  categoriesToCalendarRules,
  clearDuplicateColor,
} from "@/lib/gcalColors";

interface ConfigCardProps {
  config: Record<string, unknown>;
  onSave: (updated: Record<string, unknown>) => Promise<void>;
  saveLabel?: string;
}

const INPUT: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 8,
  padding: "6px 10px",
  fontSize: 13,
  outline: "none",
  width: "100%",
  fontFamily: "var(--font-literata)",
};

const LABEL: React.CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 4,
  display: "block",
};

const SECTION_HEADING: React.CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  marginBottom: 12,
  marginTop: 4,
};

function Field({ label, value, onChange, type = "text" }: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={LABEL}>{label}</label>
      <input
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        style={INPUT}
      />
    </div>
  );
}

export default function ConfigCard({ config, onSave, saveLabel = "Save" }: ConfigCardProps) {
  const [draft, setDraft] = useState<Record<string, unknown>>(
    JSON.parse(JSON.stringify(config))
  );
  const [categories, setCategories] = useState<ColorRule[]>(() => {
    const rules = config.calendar_rules as Record<string, unknown> | undefined;
    return rules && Object.keys(rules).length > 0
      ? calendarRulesToCategories(rules)
      : [];
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sleep = (draft.sleep ?? {}) as Record<string, unknown>;
  const scheduling = (draft.scheduling ?? {}) as Record<string, unknown>;

  const setSleep = (key: string, value: unknown) =>
    setDraft((d) => {
      const prev = (typeof d.sleep === "object" && d.sleep !== null ? d.sleep : {}) as Record<string, unknown>;
      return { ...d, sleep: { ...prev, [key]: value } };
    });

  const setScheduling = (key: string, value: unknown) =>
    setDraft((d) => {
      const prev = (typeof d.scheduling === "object" && d.scheduling !== null ? d.scheduling : {}) as Record<string, unknown>;
      return { ...d, scheduling: { ...prev, [key]: value } };
    });

  const handleCategoryChange = (index: number, updated: ColorRule) => {
    setCategories(prev => {
      let next = [...prev];
      if (updated.colorId !== null && updated.colorId !== prev[index].colorId) {
        next = clearDuplicateColor(next, updated.colorId, index);
      }
      next[index] = updated;
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

  const canSave = categories.every(c => c.name.trim() !== "");

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const updated = {
        ...draft,
        calendar_rules: categoriesToCalendarRules(categories),
      };
      await onSave(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ color: "var(--text)" }}>
      {/* Sleep */}
      <p style={SECTION_HEADING}>Sleep &amp; Schedule</p>
      <Field
        label="Wake time"
        type="time"
        value={(sleep.default_wake_time as string) ?? ""}
        onChange={(v) => setSleep("default_wake_time", v)}
      />
      <Field
        label="Morning buffer (minutes)"
        type="number"
        value={(sleep.morning_buffer_minutes as number) ?? 90}
        onChange={(v) => setSleep("morning_buffer_minutes", parseInt(v, 10) || 0)}
      />
      <Field
        label="First task not before"
        type="time"
        value={(sleep.first_task_not_before as string) ?? ""}
        onChange={(v) => setSleep("first_task_not_before", v)}
      />
      <Field
        label="No tasks after"
        value={(sleep.no_tasks_after as string) ?? ""}
        onChange={(v) => setSleep("no_tasks_after", v)}
      />

      {/* Event categories */}
      <p style={{ ...SECTION_HEADING, marginTop: 20 }}>Event categories</p>

      {categories.map((cat, i) => (
        <ColorRuleCard
          key={i}
          rule={cat}
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
          marginBottom: 4,
          fontFamily: "var(--font-literata)",
        }}
      >
        + Add event category
      </button>

      {/* Scheduling */}
      <p style={{ ...SECTION_HEADING, marginTop: 20 }}>Scheduling</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Field
          label="Min gap (min)"
          type="number"
          value={(scheduling.min_gap_between_tasks_minutes as number) ?? 5}
          onChange={(v) => setScheduling("min_gap_between_tasks_minutes", parseInt(v, 10) || 0)}
        />
        <Field
          label="Max tasks/day"
          type="number"
          value={(scheduling.max_tasks_per_day as number) ?? 10}
          onChange={(v) => setScheduling("max_tasks_per_day", parseInt(v, 10) || 0)}
        />
      </div>

      {error && (
        <p style={{ color: "var(--danger)", fontSize: 12, marginTop: 8 }}>{error}</p>
      )}

      <button
        onClick={handleSave}
        disabled={saving || !canSave}
        style={{
          marginTop: 20,
          width: "100%",
          padding: "11px 0",
          borderRadius: 10,
          background: saving || !canSave ? "var(--accent-tint)" : "var(--accent)",
          color: saving || !canSave ? "var(--accent)" : "var(--bg)",
          border: "none",
          fontSize: 14,
          fontWeight: 500,
          cursor: saving || !canSave ? "not-allowed" : "pointer",
        }}
      >
        {saving ? "Saving…" : saveLabel}
      </button>
    </div>
  );
}
