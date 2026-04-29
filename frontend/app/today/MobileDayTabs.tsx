"use client";

type Tab = "yesterday" | "today" | "tomorrow";

interface Props {
  active: Tab;
  onChange: (t: Tab) => void;
}

const LABELS: Record<Tab, string> = {
  yesterday: "Yesterday",
  today: "Today",
  tomorrow: "Tomorrow",
};

export default function MobileDayTabs({ active, onChange }: Props) {
  return (
    <div role="tablist" aria-label="Schedule day" style={{ display: "flex", gap: 6, padding: "0 0 10px" }}>
      {(["yesterday", "today", "tomorrow"] as const).map((t) => {
        const selected = active === t;
        return (
          <button
            key={t}
            id={`tab-${t}`}
            role="tab"
            aria-selected={selected}
            aria-controls="today-tabpanel"
            type="button"
            onClick={() => onChange(t)}
            style={{
              flex: 1,
              padding: "8px 0",
              background: selected ? "rgba(196,130,26,0.16)" : "transparent",
              color: selected ? "var(--accent)" : "var(--text-muted)",
              border: "1px solid",
              borderColor: selected ? "rgba(196,130,26,0.45)" : "var(--border)",
              borderRadius: 99,
              fontFamily: "var(--font-literata)",
              fontSize: 13,
              minHeight: 36,
              cursor: "pointer",
            }}
          >
            {LABELS[t]}
          </button>
        );
      })}
    </div>
  );
}
