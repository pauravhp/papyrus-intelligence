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
          background: "#6366f1",
          color: "#fff",
          border: "none",
          fontSize: 13,
          fontWeight: 500,
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.5 : 1,
          transition: "opacity 0.15s, transform 0.1s",
          letterSpacing: "0.01em",
        }}
      >
        Looks good →
      </button>
      <button
        onClick={onReject}
        disabled={disabled}
        style={{
          padding: "9px 22px",
          borderRadius: 10,
          background: "transparent",
          color: "#64748b",
          border: "1px solid rgba(255,255,255,0.08)",
          fontSize: 13,
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
