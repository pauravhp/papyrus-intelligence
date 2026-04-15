// frontend/app/dashboard/today/TodaySkeleton.tsx
"use client";

import { motion } from "framer-motion";

const pulse = {
  animate: { opacity: [0.4, 0.7, 0.4], transition: { duration: 1.5, repeat: Infinity } },
};

function SkeletonBar({ width = "100%", height = 14 }: { width?: string; height?: number }) {
  return (
    <motion.div
      {...pulse}
      style={{
        width,
        height,
        background: "var(--border)",
        borderRadius: 4,
      }}
    />
  );
}

function ColumnSkeleton({ wide }: { wide?: boolean }) {
  return (
    <div style={{ width: wide ? "100%" : 220, flexShrink: wide ? undefined : 0 }}>
      <SkeletonBar width="60%" height={18} />
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 12 }}>
        {[1, 2, 3].map(i => (
          <SkeletonBar key={i} height={12} width={`${60 + i * 10}%`} />
        ))}
      </div>
    </div>
  );
}

export default function TodaySkeleton() {
  return (
    <div style={{ padding: "32px 48px 48px" }} aria-busy="true">
      <SkeletonBar width="120px" height={32} />
      <div style={{ marginTop: 32, display: "flex", gap: 24 }}>
        <ColumnSkeleton />
        <div style={{ flex: 1, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: "20px 18px" }}>
          <ColumnSkeleton wide />
        </div>
        <ColumnSkeleton />
      </div>
    </div>
  );
}
