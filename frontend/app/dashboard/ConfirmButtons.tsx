// frontend/app/dashboard/ConfirmButtons.tsx
"use client";

interface Props {
  onConfirm: () => void;
  onReject: () => void;
  disabled?: boolean;
}

export default function ConfirmButtons({ onConfirm, onReject, disabled }: Props) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
      <button
        onClick={onConfirm}
        disabled={disabled}
        style={{
          padding: "9px 22px",
          borderRadius: 10,
          background: "var(--accent)",
          color: "var(--bg)",
          border: "none",
          fontSize: 13,
          fontFamily: "var(--font-literata)",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
          transition: "opacity 0.15s",
          letterSpacing: "0.01em",
        }}
      >
        Looks good
      </button>
      <button
        onClick={onReject}
        disabled={disabled}
        style={{
          padding: "9px 22px",
          borderRadius: 10,
          background: "transparent",
          color: "var(--text-muted)",
          border: "1px solid var(--border-strong)",
          fontSize: 13,
          fontFamily: "var(--font-literata)",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
          transition: "opacity 0.15s",
        }}
      >
        Adjust
      </button>
    </div>
  );
}
