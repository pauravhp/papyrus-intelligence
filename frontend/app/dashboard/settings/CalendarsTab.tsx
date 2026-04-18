// frontend/app/dashboard/settings/CalendarsTab.tsx
"use client";

import { useState } from "react";
import { apiPost } from "@/utils/api";
import CalendarSection from "@/components/CalendarSection";
import ColorRuleCard from "@/components/ColorRuleCard";
import {
  type ColorRule,
  calendarRulesToCategories,
  categoriesToCalendarRules,
  clearDuplicateColor,
} from "@/lib/gcalColors";

interface CalendarsTabProps {
  config: Record<string, unknown>;
  getToken: () => Promise<string>;
}

const GROUP_LABEL: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: "var(--text-faint)",
  paddingBottom: 10,
  marginBottom: 14,
  borderBottom: "1px solid var(--border)",
};

export default function CalendarsTab({ config, getToken }: CalendarsTabProps) {
  const [localConfig, setLocalConfig] = useState<Record<string, unknown>>(config);

  const [categories, setCategories] = useState<ColorRule[]>(() => {
    const rules = config.calendar_rules as Record<string, unknown> | undefined;
    return rules && Object.keys(rules).length > 0
      ? calendarRulesToCategories(rules)
      : [];
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const canSave = categories.every((c) => c.name.trim() !== "");

  const handleCategoryChange = (index: number, updated: ColorRule) => {
    setCategories((prev) => {
      let next = [...prev];
      if (updated.colorId !== null && updated.colorId !== prev[index].colorId) {
        next = clearDuplicateColor(next, updated.colorId, index);
      }
      next[index] = updated;
      return next;
    });
  };

  const handleCategoryDelete = (index: number) => {
    setCategories((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAddCategory = () => {
    setCategories((prev) => [
      ...prev,
      { name: "", colorId: null, bufferBefore: 15, bufferAfter: 15 },
    ]);
  };

  const handleSaveCategories = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const token = await getToken();
      const calendarRules = categoriesToCalendarRules(categories);
      const updated = { ...localConfig, calendar_rules: calendarRules };
      await apiPost("/api/onboard/promote", { config: updated }, token);
      setLocalConfig(updated);
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
      {/* Source + write calendar — CalendarSection handles its own save via PATCH /api/settings/calendars */}
      <CalendarSection
        config={localConfig}
        onConfigUpdate={(patch) =>
          setLocalConfig((prev) => ({ ...prev, ...patch }))
        }
      />

      <div style={{ marginTop: 28 }}>
        <p style={GROUP_LABEL}>Event categories</p>
        <p style={{ fontSize: 12, color: "var(--text-faint)", fontStyle: "italic", marginBottom: 14, lineHeight: 1.55, maxWidth: "52ch" }}>
          Tell Papyrus what your calendar colors mean so it can add the right buffers.
        </p>

        {categories.map((cat, i) => (
          <ColorRuleCard
            key={i}
            rule={cat}
            onChange={(updated) => handleCategoryChange(i, updated)}
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
            marginBottom: 16,
            fontFamily: "var(--font-literata)",
            transition: "color 0.15s, border-color 0.15s",
          }}
        >
          + Add event category
        </button>

        {error && (
          <p style={{ color: "var(--danger)", fontSize: 12, marginBottom: 12 }}>{error}</p>
        )}

        <button
          onClick={handleSaveCategories}
          disabled={saving || !canSave}
          style={{
            padding: "10px 22px",
            background: saving || !canSave ? "var(--accent-tint)" : "var(--accent)",
            color: saving || !canSave ? "var(--accent)" : "var(--bg)",
            border: "none",
            borderRadius: 9,
            fontFamily: "var(--font-literata)",
            fontSize: 13,
            fontWeight: 500,
            cursor: saving || !canSave ? "not-allowed" : "pointer",
            transition: "background 0.15s",
          }}
        >
          {saved ? "Saved" : saving ? "Saving…" : "Save categories"}
        </button>
      </div>
    </div>
  );
}
