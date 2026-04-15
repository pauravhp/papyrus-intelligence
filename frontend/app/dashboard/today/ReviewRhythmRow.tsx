// frontend/app/dashboard/today/ReviewRhythmRow.tsx

export interface ReviewRhythm {
  id: number;
  rhythm_name: string;
}

export interface ReviewRhythmState {
  completed: boolean | null; // null = unanswered
}

interface ReviewRhythmRowProps {
  rhythm: ReviewRhythm;
  state: ReviewRhythmState;
  onChange: (rhythmId: number, completed: boolean) => void;
}

export default function ReviewRhythmRow({ rhythm, state, onChange }: ReviewRhythmRowProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span
        style={{
          fontSize: 14,
          fontFamily: "var(--font-literata)",
          color: "var(--text)",
        }}
      >
        {rhythm.rhythm_name}
      </span>

      <div style={{ display: "flex", gap: 8 }}>
        {(["Yes", "No"] as const).map((label) => {
          const isYes = label === "Yes";
          const isActive = state.completed === isYes;
          return (
            <button
              key={label}
              onClick={() => onChange(rhythm.id, isYes)}
              style={{
                padding: "4px 16px",
                borderRadius: 20,
                border: `1px solid ${isActive ? (isYes ? "var(--accent)" : "var(--border)") : "var(--border)"}`,
                background: isActive
                  ? isYes
                    ? "var(--accent-soft, #f0e0c0)"
                    : "var(--done-bg, #f0ece4)"
                  : "var(--surface-raised, #fff9f0)",
                fontFamily: "var(--font-literata)",
                fontSize: 12,
                color: isActive && isYes ? "var(--accent)" : "var(--text-secondary, #7a5c3e)",
                cursor: "pointer",
                transition: "all 0.12s ease",
              }}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
