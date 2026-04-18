// frontend/app/dashboard/settings/NudgesTab.tsx
"use client";

import { useState } from "react";
import { apiPatch } from "@/utils/api";

interface NudgesTabProps {
  config: Record<string, unknown>;
  getToken: () => Promise<string>;
}

type NudgeKey = "coaching_enabled" | "weekly_reflection_enabled";

const NUDGES: { key: NudgeKey; name: string; description: string }[] = [
  {
    key: "coaching_enabled",
    name: "Coaching nudges",
    description:
      "One gentle observation per conversation — a project without a deadline, a task that keeps slipping. Never raised again if you dismiss it.",
  },
  {
    key: "weekly_reflection_enabled",
    name: "Weekly reflection",
    description:
      "A short note each Friday on what you shipped — what you built, not what you didn't finish.",
  },
];

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        position: "relative",
        width: 34,
        height: 19,
        flexShrink: 0,
        marginTop: 3,
        cursor: "pointer",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: 10,
          background: on ? "var(--accent)" : "var(--border-strong)",
          transition: "background 0.2s",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 2.5,
          left: 2.5,
          width: 14,
          height: 14,
          borderRadius: "50%",
          background: "var(--bg)",
          transform: on ? "translateX(15px)" : "translateX(0)",
          transition: "transform 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
}

export default function NudgesTab({ config, getToken }: NudgesTabProps) {
  const initNudges = (config.nudges ?? {}) as Record<string, boolean>;

  const [values, setValues] = useState<Record<NudgeKey, boolean>>({
    coaching_enabled:            initNudges.coaching_enabled            ?? true,
    weekly_reflection_enabled:   initNudges.weekly_reflection_enabled   ?? true,
  });

  const handleToggle = async (key: NudgeKey) => {
    const prev = values[key];
    const next = !prev;

    // Optimistic update
    setValues((v) => ({ ...v, [key]: next }));

    try {
      const token = await getToken();
      await apiPatch("/api/settings/nudges", { [key]: next }, token);
    } catch {
      // Revert on error
      setValues((v) => ({ ...v, [key]: prev }));
    }
  };

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--text-muted)", fontStyle: "italic", marginBottom: 20, maxWidth: "52ch", lineHeight: 1.55 }}>
        Things Papyrus notices but keeps to itself, unless you want to hear them.
      </p>

      <div style={{ borderTop: "1px solid var(--border)" }}>
        {NUDGES.map(({ key, name, description }) => (
          <div
            key={key}
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 24,
              padding: "18px 0",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 14, color: "var(--text)" }}>{name}</p>
              <p style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic", marginTop: 3, lineHeight: 1.55, maxWidth: "46ch" }}>
                {description}
              </p>
            </div>
            <Toggle on={values[key]} onClick={() => handleToggle(key)} />
          </div>
        ))}
      </div>
    </div>
  );
}
