// frontend/app/dashboard/settings/SettingsClient.tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { createClient } from "@/utils/supabase/client";
import IntegrationsTab from "./IntegrationsTab";
import ScheduleTab from "./ScheduleTab";
import CalendarsTab from "./CalendarsTab";
import NudgesTab from "./NudgesTab";

type Tab = "integrations" | "schedule" | "calendars" | "nudges";

const COACHING_NUDGES_ENABLED = process.env.NEXT_PUBLIC_COACHING_NUDGES_ENABLED === "true";

const TABS: { id: Tab; label: string }[] = [
  { id: "integrations", label: "Integrations" },
  { id: "schedule",     label: "Schedule"     },
  { id: "calendars",    label: "Calendars"    },
  ...(COACHING_NUDGES_ENABLED ? [{ id: "nudges" as Tab, label: "Nudges" }] : []),
];

interface SettingsData {
  config: Record<string, unknown>;
  gcalConnected: boolean;
  todoistConnected: boolean;
}

export default function SettingsClient() {
  const [activeTab, setActiveTab] = useState<Tab>("integrations");
  const [data, setData] = useState<SettingsData | null>(null);
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;

  useEffect(() => {
    supabase
      .from("users")
      .select("config, google_credentials, todoist_oauth_token")
      .maybeSingle()
      .then(({ data: row }) => {
        setData({
          config: (row?.config as Record<string, unknown>) ?? {},
          gcalConnected: !!row?.google_credentials,
          todoistConnected: !!row?.todoist_oauth_token,
        });
      });
  }, [supabase]);

  const getToken = useCallback(async () => {
    const { data: session } = await supabase.auth.getSession();
    return session.session?.access_token ?? "";
  }, [supabase]);

  if (!data) {
    return (
      <div style={{ paddingTop: 32 }}>
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading…</p>
      </div>
    );
  }

  return (
    <div>
      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          marginTop: 28,
          borderBottom: "1px solid var(--border)",
        }}
      >
        {TABS.map(({ id, label }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                padding: "0 2px 11px",
                marginRight: 26,
                fontFamily: "var(--font-literata)",
                fontSize: 13,
                color: active ? "var(--text)" : "var(--text-muted)",
                cursor: "pointer",
                border: "none",
                background: "transparent",
                position: "relative",
                outline: "none",
                transition: "color 0.15s",
                whiteSpace: "nowrap",
              }}
            >
              {label}
              {active && (
                <motion.div
                  layoutId="tab-underline"
                  style={{
                    position: "absolute",
                    bottom: -1,
                    left: 0,
                    right: 0,
                    height: 1.5,
                    background: "var(--accent)",
                  }}
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div style={{ paddingTop: 32 }}>
        {activeTab === "integrations" && (
          <IntegrationsTab
            gcalConnected={data.gcalConnected}
            todoistConnected={data.todoistConnected}
            getToken={getToken}
          />
        )}
        {activeTab === "schedule" && (
          <ScheduleTab config={data.config} getToken={getToken} />
        )}
        {activeTab === "calendars" && (
          <CalendarsTab config={data.config} getToken={getToken} />
        )}
        {activeTab === "nudges" && COACHING_NUDGES_ENABLED && (
          <NudgesTab config={data.config} getToken={getToken} />
        )}
      </div>
    </div>
  );
}
