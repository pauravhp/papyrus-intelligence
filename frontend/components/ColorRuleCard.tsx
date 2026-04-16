"use client";

import {
  ColorRule,
  GCAL_COLOR_HEX,
  GCAL_COLOR_NAMES,
  NAME_MAX_LENGTH,
  NAME_REGEX,
} from "@/lib/gcalColors";

interface ColorRuleCardProps {
  rule: ColorRule;
  detectedHint?: string;
  onChange: (updated: ColorRule) => void;
  onDelete: () => void;
}

const PRESETS: { label: string; value: 0 | 5 | 15 | 30 }[] = [
  { label: "None", value: 0 },
  { label: "Short · 5m", value: 5 },
  { label: "Medium · 15m", value: 15 },
  { label: "Long · 30m", value: 30 },
];

const LABEL: React.CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 10,
  fontWeight: 500,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 6,
  display: "block",
};

export default function ColorRuleCard({
  rule,
  detectedHint,
  onChange,
  onDelete,
}: ColorRuleCardProps) {
  const handleNameChange = (v: string) => {
    if (v.length <= NAME_MAX_LENGTH && NAME_REGEX.test(v)) {
      onChange({ ...rule, name: v });
    }
  };

  return (
    <div
      style={{
        background: "var(--surface-raised)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "16px",
        marginBottom: 10,
        position: "relative",
      }}
    >
      {/* Delete */}
      <button
        onClick={onDelete}
        aria-label="Remove category"
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          background: "none",
          border: "none",
          color: "var(--text-faint)",
          fontSize: 18,
          lineHeight: 1,
          cursor: "pointer",
          padding: "2px 5px",
          borderRadius: 4,
        }}
      >
        ×
      </button>

      {/* Detected hint (onboarding only) */}
      {detectedHint && (
        <p
          style={{
            fontSize: 11,
            color: "var(--text-faint)",
            fontStyle: "italic",
            marginBottom: 10,
          }}
        >
          {detectedHint}
        </p>
      )}

      {/* Name input */}
      <input
        value={rule.name}
        onChange={(e) => handleNameChange(e.target.value)}
        maxLength={NAME_MAX_LENGTH}
        placeholder="Category name"
        style={{
          background: "transparent",
          border: "none",
          borderBottom: `1px solid ${rule.name.trim() === "" ? "var(--danger)" : "var(--border-strong)"}`,
          color: "var(--text)",
          fontSize: 14,
          fontWeight: 600,
          padding: "2px 0 5px",
          width: "calc(100% - 28px)",
          outline: "none",
          fontFamily: "var(--font-literata)",
          marginBottom: 14,
        }}
      />
      {rule.name.trim() === "" && (
        <p style={{ fontSize: 10, color: "var(--danger)", marginTop: -10, marginBottom: 8 }}>
          Name required
        </p>
      )}

      {/* Colour swatch picker */}
      <span style={LABEL}>Colour on your calendar</span>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        {Object.entries(GCAL_COLOR_NAMES).map(([id, name]) => (
          <button
            key={id}
            title={name}
            aria-label={name}
            aria-pressed={rule.colorId === id}
            onClick={() => onChange({ ...rule, colorId: id })}
            style={{
              width: 22,
              height: 22,
              borderRadius: "50%",
              background: GCAL_COLOR_HEX[id],
              border: rule.colorId === id ? "2.5px solid var(--text)" : "2.5px solid transparent",
              cursor: "pointer",
              padding: 0,
              transform: rule.colorId === id ? "scale(1.1)" : "scale(1)",
              transition: "transform 0.12s",
              flexShrink: 0,
            }}
          />
        ))}
      </div>
      {rule.colorId === null && (
        <p style={{ fontSize: 10, color: "var(--text-faint)", fontStyle: "italic", marginTop: -10, marginBottom: 10 }}>
          No colour selected — this rule won&#39;t match calendar events
        </p>
      )}

      {/* Buffer before */}
      <span style={LABEL}>Buffer before</span>
      <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
        {PRESETS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => onChange({ ...rule, bufferBefore: value })}
            style={{
              flex: 1,
              padding: "6px 0",
              borderRadius: 8,
              border: `1px solid ${rule.bufferBefore === value ? "var(--accent)" : "var(--border-strong)"}`,
              background: rule.bufferBefore === value ? "var(--accent-tint)" : "var(--surface)",
              color: rule.bufferBefore === value ? "var(--accent)" : "var(--text-muted)",
              fontSize: 11,
              fontWeight: rule.bufferBefore === value ? 600 : 400,
              cursor: "pointer",
              fontFamily: "var(--font-literata)",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Buffer after */}
      <span style={LABEL}>Buffer after</span>
      <div style={{ display: "flex", gap: 6 }}>
        {PRESETS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => onChange({ ...rule, bufferAfter: value })}
            style={{
              flex: 1,
              padding: "6px 0",
              borderRadius: 8,
              border: `1px solid ${rule.bufferAfter === value ? "var(--accent)" : "var(--border-strong)"}`,
              background: rule.bufferAfter === value ? "var(--accent-tint)" : "var(--surface)",
              color: rule.bufferAfter === value ? "var(--accent)" : "var(--text-muted)",
              fontSize: 11,
              fontWeight: rule.bufferAfter === value ? 600 : 400,
              cursor: "pointer",
              fontFamily: "var(--font-literata)",
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
