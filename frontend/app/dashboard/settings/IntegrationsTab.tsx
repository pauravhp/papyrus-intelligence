// frontend/app/dashboard/settings/IntegrationsTab.tsx
"use client";

import { CalendarDays, CheckSquare } from "lucide-react";

interface IntegrationsTabProps {
  gcalConnected: boolean;
  todoistConnected: boolean;
  getToken: () => Promise<string>;
}

const REDIRECT_AFTER = "/dashboard/settings";

function IntegrationRow({
  icon: Icon,
  name,
  description,
  connected,
  onReconnect,
}: {
  icon: React.ElementType;
  name: string;
  description: string;
  connected: boolean;
  onReconnect: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 16,
        padding: "16px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 9,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <Icon size={16} color="var(--text-muted)" />
        </div>
        <div>
          <p style={{ fontSize: 14, color: "var(--text)" }}>{name}</p>
          {connected ? (
            <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
              <div
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: "var(--accent)",
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 11, color: "var(--accent)", fontStyle: "italic" }}>
                Connected
              </span>
            </div>
          ) : (
            <p style={{ fontSize: 11, color: "var(--text-faint)", fontStyle: "italic", marginTop: 2 }}>
              Not connected
            </p>
          )}
        </div>
      </div>
      <button
        onClick={onReconnect}
        style={{
          padding: "7px 14px",
          background: "transparent",
          color: connected ? "var(--text-muted)" : "var(--accent)",
          border: `1px solid ${connected ? "var(--border-strong)" : "var(--accent)"}`,
          borderRadius: 8,
          fontFamily: "var(--font-literata)",
          fontSize: 12,
          cursor: "pointer",
          flexShrink: 0,
          transition: "all 0.15s",
        }}
      >
        {connected ? "Reconnect" : "Connect"}
      </button>
    </div>
  );
}

export default function IntegrationsTab({ gcalConnected, todoistConnected, getToken }: IntegrationsTabProps) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  const handleReconnectGoogle = async () => {
    const token = await getToken();
    window.location.href = `${apiUrl}/auth/google?token=${token}&redirect_after=${encodeURIComponent(REDIRECT_AFTER)}`;
  };

  const handleReconnectTodoist = async () => {
    const token = await getToken();
    window.location.href = `${apiUrl}/auth/todoist?token=${token}&redirect_after=${encodeURIComponent(REDIRECT_AFTER)}`;
  };

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--text-muted)", fontStyle: "italic", marginBottom: 20, maxWidth: "52ch", lineHeight: 1.55 }}>
        Reconnect a service if something stops working. Your data and settings stay intact.
      </p>

      <div style={{ borderTop: "1px solid var(--border)" }}>
        <IntegrationRow
          icon={CalendarDays}
          name="Google Calendar"
          description="Reads and writes your events."
          connected={gcalConnected}
          onReconnect={handleReconnectGoogle}
        />
        <IntegrationRow
          icon={CheckSquare}
          name="Todoist"
          description="Reads your tasks and sets due times."
          connected={todoistConnected}
          onReconnect={handleReconnectTodoist}
        />
      </div>
    </div>
  );
}
