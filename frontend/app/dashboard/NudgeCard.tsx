"use client";

import { useState } from "react";

export interface NudgeCardData {
  nudge_id: string;
  coach_message: string;
  learn_more_path: string;
  action_label: string | null;
  instance_key: string | null;
}

interface NudgeCardProps {
  nudge: NudgeCardData;
  token: string;
  apiBase: string;
  onDismiss: () => void;
  onAction: (actionLabel: string) => void;
}

export default function NudgeCard({ nudge, token, apiBase, onDismiss, onAction }: NudgeCardProps) {
  const [dismissing, setDismissing] = useState(false);

  const dismiss = async (instanceKey: string | null) => {
    if (dismissing) return;
    setDismissing(true);
    try {
      await fetch(`${apiBase}/api/nudge/dismiss`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          nudge_type: nudge.nudge_id,
          instance_key: instanceKey,
          mode: "forever",
        }),
      });
    } catch {
      // Dismiss is best-effort — hide card regardless
    }
    onDismiss();
  };

  const stopAllNudges = async () => {
    try {
      await fetch(`${apiBase}/api/settings/nudges`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          disabled_types: [nudge.nudge_id],
        }),
      });
    } catch {
      // Best-effort
    }
    onDismiss();
  };

  return (
    <div
      style={{
        background: "var(--bg)",
        borderLeft: "3px solid var(--accent)",
        border: "1px solid rgba(196,130,26,0.22)",
        borderLeftWidth: 3,
        borderRadius: 8,
        padding: "10px 12px",
        position: "relative",
      }}
    >
      {/* Dismiss × */}
      <button
        onClick={() => dismiss(nudge.instance_key)}
        aria-label="Dismiss nudge"
        style={{
          position: "absolute",
          top: 8,
          right: 10,
          background: "transparent",
          border: "none",
          color: "var(--text-faint)",
          cursor: "pointer",
          fontSize: 13,
          lineHeight: 1,
          padding: 2,
        }}
      >
        ✕
      </button>

      {/* Label */}
      <p
        style={{
          fontSize: 8,
          fontWeight: 700,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "var(--accent)",
          marginBottom: 6,
          fontFamily: "var(--font-literata)",
        }}
      >
        Coaching
      </p>

      {/* Coach message */}
      <p
        style={{
          fontSize: 12,
          lineHeight: 1.65,
          color: "var(--text)",
          fontFamily: "var(--font-literata)",
          marginBottom: 10,
          paddingRight: 16,
        }}
      >
        {nudge.coach_message}
      </p>

      {/* CTAs */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <a
          href={nudge.learn_more_path}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            padding: "3px 9px",
            border: "1px solid var(--border-strong)",
            borderRadius: 5,
            fontSize: 10,
            color: "var(--text-muted)",
            fontFamily: "var(--font-literata)",
            textDecoration: "none",
            display: "inline-block",
          }}
        >
          The science →
        </a>

        {nudge.action_label && (
          <button
            onClick={() => onAction(nudge.action_label!)}
            style={{
              padding: "3px 9px",
              border: "none",
              borderRadius: 5,
              background: "var(--accent-tint)",
              fontSize: 10,
              color: "var(--accent)",
              fontFamily: "var(--font-literata)",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {nudge.action_label}
          </button>
        )}
      </div>

      {/* Stop all nudges of this type */}
      <button
        onClick={stopAllNudges}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--text-faint)",
          fontSize: 9,
          fontFamily: "var(--font-literata)",
          cursor: "pointer",
          marginTop: 8,
          padding: 0,
          textDecoration: "underline",
          textDecorationStyle: "dotted",
          textUnderlineOffset: 2,
        }}
      >
        Stop these nudges
      </button>
    </div>
  );
}
