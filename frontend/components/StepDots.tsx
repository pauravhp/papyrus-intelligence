type StepDotsProps = { current: number; total?: number };

export default function StepDots({ current, total = 4 }: StepDotsProps) {
  return (
    <div className="flex gap-2 justify-center">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className="block transition-all duration-300"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background:
              i < current
                ? "#6366f1" // completed
                : i === current
                  ? "#818cf8" // active
                  : "transparent", // upcoming
            border: `1.5px solid ${i <= current ? "#6366f1" : "rgba(255,255,255,0.18)"}`,
            boxShadow:
              i === current ? "0 0 8px rgba(99,102,241,0.65)" : "none",
          }}
        />
      ))}
    </div>
  );
}
