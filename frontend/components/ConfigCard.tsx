// frontend/components/ConfigCard.tsx
"use client";

import { useState } from "react";

interface ConfigCardProps {
  config: Record<string, unknown>;
  onSave: (updated: Record<string, unknown>) => Promise<void>;
  saveLabel?: string;
}

const INPUT: React.CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  border: "1px solid rgba(255,255,255,0.1)",
  color: "#f8fafc",
  borderRadius: 8,
  padding: "6px 10px",
  fontSize: 13,
  outline: "none",
  width: "100%",
};

const LABEL: React.CSSProperties = {
  color: "#94a3b8",
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 4,
  display: "block",
};

const SECTION_HEADING: React.CSSProperties = {
  color: "#64748b",
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sleep = (draft.sleep ?? {}) as Record<string, unknown>;
  const scheduling = (draft.scheduling ?? {}) as Record<string, unknown>;
  const calRules = (draft.calendar_rules ?? {}) as Record<string, Record<string, unknown>>;

  const setSleep = (key: string, value: unknown) =>
    setDraft((d) => ({ ...d, sleep: { ...(d.sleep as object), [key]: value } }));

  const setScheduling = (key: string, value: unknown) =>
    setDraft((d) => ({ ...d, scheduling: { ...(d.scheduling as object), [key]: value } }));

  const setCalRule = (ruleName: string, key: string, value: unknown) =>
    setDraft((d) => ({
      ...d,
      calendar_rules: {
        ...(d.calendar_rules as object),
        [ruleName]: { ...(calRules[ruleName] ?? {}), [key]: value },
      },
    }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ color: "#f8fafc" }}>
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

      {/* Calendar rules */}
      {Object.keys(calRules).length > 0 && (
        <>
          <p style={{ ...SECTION_HEADING, marginTop: 20 }}>Calendar Rules</p>
          {Object.entries(calRules).map(([name, rule]) => (
            <div
              key={name}
              style={{
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.07)",
                borderRadius: 10,
                padding: "12px 14px",
                marginBottom: 10,
              }}
            >
              <p style={{ color: "#818cf8", fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
                {name}
              </p>
              <Field
                label="Color ID"
                value={(rule.color_id as string) ?? ""}
                onChange={(v) => setCalRule(name, "color_id", v)}
              />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <Field
                  label="Buffer before (min)"
                  type="number"
                  value={(rule.buffer_before_minutes as number) ?? 0}
                  onChange={(v) => setCalRule(name, "buffer_before_minutes", parseInt(v, 10) || 0)}
                />
                <Field
                  label="Buffer after (min)"
                  type="number"
                  value={(rule.buffer_after_minutes as number) ?? 0}
                  onChange={(v) => setCalRule(name, "buffer_after_minutes", parseInt(v, 10) || 0)}
                />
              </div>
            </div>
          ))}
        </>
      )}

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
        <p style={{ color: "#f43f5e", fontSize: 12, marginTop: 8 }}>{error}</p>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          marginTop: 20,
          width: "100%",
          padding: "11px 0",
          borderRadius: 10,
          background: saving ? "rgba(99,102,241,0.5)" : "#6366f1",
          color: "#fff",
          border: "none",
          fontSize: 14,
          fontWeight: 500,
          cursor: saving ? "not-allowed" : "pointer",
          boxShadow: saving ? "none" : "0 0 18px rgba(99,102,241,0.35)",
        }}
      >
        {saving ? "Saving…" : saveLabel}
      </button>
    </div>
  );
}
