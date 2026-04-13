// frontend/components/StepDots.tsx
type StepDotsProps = { current: number; total?: number };

export default function StepDots({ current, total = 4 }: StepDotsProps) {
  return (
    <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          style={{
            display: "block",
            width: 8,
            height: 8,
            borderRadius: "50%",
            transition: "all 0.3s",
            background:
              i < current
                ? "var(--accent)"
                : i === current
                  ? "var(--accent)"
                  : "transparent",
            border: `1.5px solid ${i <= current ? "var(--accent)" : "var(--border-strong)"}`,
            opacity: i < current ? 0.6 : 1,
            boxShadow: "none",
          }}
        />
      ))}
    </div>
  );
}
