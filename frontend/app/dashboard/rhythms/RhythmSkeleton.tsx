// frontend/app/dashboard/rhythms/RhythmSkeleton.tsx
export default function RhythmSkeleton() {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "20px 22px",
        animation: "rhythmPulse 1.8s ease-in-out infinite",
      }}
    >
      {/* Name + pill row */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 14 }}>
        <div style={{ height: 19, width: 120, borderRadius: 4, background: "var(--surface-raised)" }} />
        <div style={{ height: 17, width: 64, borderRadius: 5, background: "var(--surface-raised)" }} />
      </div>
      {/* Body row */}
      <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
        <div style={{ height: 44, width: 52, borderRadius: 4, background: "var(--surface-raised)" }} />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, flex: 1 }}>
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
              <div style={{ height: 9, width: 9, borderRadius: 2, background: "var(--surface-raised)" }} />
              <div style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--surface-raised)" }} />
            </div>
          ))}
        </div>
      </div>
      <style>{`@keyframes rhythmPulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
    </div>
  );
}
