"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { HelpCircle } from "lucide-react";

interface FieldTooltipProps {
  content: string;
}

export default function FieldTooltip({ content }: FieldTooltipProps) {
  return (
    <Tooltip.Root delayDuration={300}>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          aria-label="More information"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 13,
            height: 13,
            borderRadius: "50%",
            border: "1px solid var(--border-strong)",
            background: "transparent",
            color: "var(--text-faint)",
            cursor: "pointer",
            padding: 0,
            flexShrink: 0,
            transition: "border-color 0.15s, color 0.15s",
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--accent)";
            (e.currentTarget as HTMLButtonElement).style.color = "var(--accent)";
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border-strong)";
            (e.currentTarget as HTMLButtonElement).style.color = "var(--text-faint)";
          }}
        >
          <HelpCircle size={8} strokeWidth={2.5} />
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={6}
          style={{
            background: "var(--text)",
            color: "var(--bg)",
            fontSize: 11.5,
            fontFamily: "var(--font-literata)",
            fontStyle: "italic",
            lineHeight: 1.5,
            padding: "8px 10px",
            borderRadius: 8,
            maxWidth: 220,
            boxShadow: "0 4px 16px rgba(44,26,14,0.2)",
            zIndex: 9999,
          }}
        >
          {content}
          <Tooltip.Arrow style={{ fill: "var(--text)" }} />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
