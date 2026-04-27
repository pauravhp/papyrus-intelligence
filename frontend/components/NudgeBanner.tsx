// frontend/components/NudgeBanner.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/utils/supabase/client";
import { apiPatch } from "@/utils/api";

export interface SetupNudge {
  show: boolean;
  needs_calendar: boolean;
  needs_todoist: boolean;
}

function buildCopy(needsCalendar: boolean, needsTodoist: boolean): { title: string; body: string } {
  if (needsCalendar && needsTodoist) {
    return {
      title: "Finish connecting Papyrus",
      body: "Your Google Calendar and Todoist aren’t linked yet. Connect them so Papyrus can read your tasks and write your schedule.",
    };
  }
  if (needsTodoist) {
    return {
      title: "Connect Todoist",
      body: "Papyrus needs your tasks to plan your day. Link your Todoist account to get started.",
    };
  }
  return {
    title: "Your calendars haven’t been set up yet",
    body: "Papyrus is reading from your primary calendar only.",
  };
}

export default function NudgeBanner({ nudge }: { nudge: SetupNudge | null }) {
  const router = useRouter();
  const [dismissed, setDismissed] = useState(false);

  if (!nudge?.show || dismissed) return null;

  const { title, body } = buildCopy(nudge.needs_calendar, nudge.needs_todoist);

  const handleOpenSettings = () => {
    router.push("/dashboard/settings");
  };

  const handleDismiss = async () => {
    setDismissed(true);
    try {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";
      await apiPatch("/api/settings/calendars", { nudge_dismissed: true }, token);
    } catch {
      // fire-and-forget — UI already hidden optimistically
    }
  };

  return (
    <div style={{
      background: "var(--accent-tint)",
      border: "1px solid rgba(196,130,26,0.28)",
      borderRadius: 10,
      padding: "12px 16px",
      display: "flex",
      alignItems: "flex-start",
      gap: 12,
      marginBottom: 16,
    }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
        stroke="var(--accent)" strokeWidth="1.8"
        style={{ flexShrink: 0, marginTop: 1 }}>
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <div style={{ flex: 1 }}>
        <p style={{ fontSize: 13, color: "var(--text)", fontWeight: 500, marginBottom: 3, lineHeight: 1.4 }}>
          {title}
        </p>
        <p style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
          {body}{" "}
          <button
            onClick={handleOpenSettings}
            style={{
              fontSize: 12,
              color: "var(--accent)",
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontFamily: "var(--font-literata)",
              textDecoration: "underline",
              textDecorationStyle: "dotted",
              textUnderlineOffset: "2px",
            }}
          >
            Open Integrations &rarr;
          </button>
        </p>
      </div>
      <button
        onClick={handleDismiss}
        aria-label="Dismiss"
        style={{
          width: 24, height: 24,
          borderRadius: 6,
          border: "none", background: "none",
          color: "var(--text-faint)",
          cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
          stroke="currentColor" strokeWidth="1.8">
          <line x1="1" y1="1" x2="11" y2="11"/>
          <line x1="11" y1="1" x2="1" y2="11"/>
        </svg>
      </button>
    </div>
  );
}
