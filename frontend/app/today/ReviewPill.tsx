interface ReviewPillProps {
  onClick: () => void;
}

export default function ReviewPill({ onClick }: ReviewPillProps) {
  return (
    <button
      onClick={onClick}
      aria-label="Review"
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "8px 16px", background: "var(--surface)",
        color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8,
        fontSize: 13, fontFamily: "var(--font-literata)", cursor: "pointer",
        fontWeight: 500, letterSpacing: "0.01em", transition: "background 0.15s",
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--accent-soft, #f0e0c0)"; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "var(--surface)"; }}
    >
      Review →
    </button>
  );
}
