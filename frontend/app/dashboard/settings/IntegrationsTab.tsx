// frontend/app/dashboard/settings/IntegrationsTab.tsx
"use client";

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, CalendarDays, CheckSquare } from "lucide-react";
import { apiFetch } from "@/utils/api";
import Toast, { type ToastState } from "@/components/Toast";

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
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

  const [syncDetected, setSyncDetected] = useState<boolean | null>(null);
  const [syncCheckLoading, setSyncCheckLoading] = useState(false);
  const [syncRecheckedAtLeastOnce, setSyncRecheckedAtLeastOnce] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const runSyncDetection = useCallback(async (): Promise<{ ok: boolean; detected: boolean }> => {
    setSyncCheckLoading(true);
    try {
      const token = await getToken();
      const result = await apiFetch<{ detected: boolean; calendar_id: string | null }>(
        "/api/onboard/detect-todoist-sync",
        token,
      );
      setSyncDetected(result.detected);
      return { ok: true, detected: result.detected };
    } catch {
      setSyncDetected(false);
      return { ok: false, detected: false };
    } finally {
      setSyncCheckLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (gcalConnected && todoistConnected && syncDetected === null && !syncCheckLoading) {
      void runSyncDetection();
    }
  }, [gcalConnected, todoistConnected, syncDetected, syncCheckLoading, runSyncDetection]);

  const handleRecheck = useCallback(async () => {
    setSyncRecheckedAtLeastOnce(true);
    const result = await runSyncDetection();
    if (!result.ok) {
      setToast({ message: "Re-check failed", tone: "error" });
    } else if (result.detected) {
      setToast({ message: "Sync still detected", tone: "error" });
    } else {
      setToast({ message: "Sync cleared", tone: "success" });
    }
  }, [runSyncDetection]);

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

      {syncDetected === true && (
        <div
          style={{
            background: "var(--surface-raised)",
            border: "1px solid #d4a55a",
            borderRadius: 10,
            padding: 14,
            marginBottom: 20,
            display: "flex",
            gap: 12,
            alignItems: "flex-start",
          }}
        >
          <div style={{ background: "rgba(212, 165, 90, 0.15)", padding: 8, borderRadius: 8, flexShrink: 0 }}>
            <AlertTriangle size={16} color="#d4a55a" />
          </div>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13, color: "var(--text)", fontWeight: 500 }}>
              Todoist is mirroring tasks to your Calendar
            </p>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, lineHeight: 1.55, maxWidth: "52ch" }}>
              Papyrus writes events directly. Leaving Todoist's Google Calendar
              integration on duplicates every scheduled task on your calendar.
              Turn it off in Todoist's settings.
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <a
                href="https://app.todoist.com/app/settings/integrations/calendar"
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  background: "var(--accent)",
                  color: "var(--bg)",
                  padding: "6px 12px",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  textDecoration: "none",
                  display: "inline-block",
                }}
              >
                Open Todoist settings
              </a>
              <button
                onClick={handleRecheck}
                disabled={syncCheckLoading}
                style={{
                  background: "transparent",
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border-strong)",
                  padding: "6px 12px",
                  borderRadius: 6,
                  fontSize: 12,
                  cursor: syncCheckLoading ? "wait" : "pointer",
                }}
              >
                {syncCheckLoading ? "Re-checking…" : "Re-check"}
              </button>
            </div>
            {syncRecheckedAtLeastOnce && !syncCheckLoading && (
              <p style={{ marginTop: 8, fontSize: 11, color: "var(--text-faint)", lineHeight: 1.4 }}>
                Google Calendar can take ~60 seconds to reflect the change after you toggle the integration off in Todoist.
              </p>
            )}
          </div>
        </div>
      )}

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
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
