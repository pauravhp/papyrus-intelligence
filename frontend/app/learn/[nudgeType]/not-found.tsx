import Link from "next/link";

export default function NudgeNotFound() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        color: "var(--text)",
        fontFamily: "var(--font-literata), Georgia, serif",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <p style={{ fontSize: 14, color: "var(--text-muted)", fontStyle: "italic" }}>
        This nudge no longer exists.
      </p>
      <Link href="/dashboard" style={{ fontSize: 13, color: "var(--accent)" }}>
        Back to today →
      </Link>
    </div>
  );
}
