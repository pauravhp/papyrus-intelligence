// frontend/app/dashboard/today/ReplanButton.tsx
"use client";

interface ReplanButtonProps {
  onClick: () => void;
}

export default function ReplanButton({ onClick }: ReplanButtonProps) {
  return (
    <button
      onClick={onClick}
      aria-label="Replan your afternoon"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "8px 16px",
        background: "var(--accent)",
        color: "var(--surface)",
        border: "none",
        borderRadius: 8,
        fontSize: 13,
        fontFamily: "var(--font-literata)",
        cursor: "pointer",
        fontWeight: 500,
        letterSpacing: "0.01em",
      }}
    >
      <span aria-hidden>↻</span>
      Replan afternoon
    </button>
  );
}
