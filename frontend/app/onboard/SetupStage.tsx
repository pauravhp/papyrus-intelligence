"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, CalendarDays, CheckSquare, AlertTriangle } from "lucide-react";
import { createClient } from "@/utils/supabase/client";
import { apiFetch } from "@/utils/api";

const CARD: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  padding: "20px",
};

interface SetupStageProps {
  onAdvance: (timezone: string, calendarIds: string[]) => void;
}

export default function SetupStage({ onAdvance }: SetupStageProps) {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;
  const [gcalConnected, setGcalConnected] = useState(false);
  const [todoistConnected, setTodoistConnected] = useState(false);
  const [checking, setChecking] = useState(true);
  const [syncDetected, setSyncDetected] = useState<boolean | null>(null);
  const [syncCheckLoading, setSyncCheckLoading] = useState(false);
  // True after the user clicks Re-check and detection still came back positive,
  // OR after they clicked Re-check at least once. Used to surface the "Google
  // takes ~60s to update" hint only when it's actionable.
  const [syncRecheckedAtLeastOnce, setSyncRecheckedAtLeastOnce] = useState(false);

  useEffect(() => {
    supabase
      .from("users")
      .select("google_credentials, todoist_oauth_token")
      .maybeSingle()
      .then(({ data }) => {
        setGcalConnected(!!data?.google_credentials);
        setTodoistConnected(!!data?.todoist_oauth_token);
        setChecking(false);
      });
  }, []);

  const runSyncDetection = useCallback(async () => {
    setSyncCheckLoading(true);
    try {
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";
      const result = await apiFetch<{ detected: boolean; calendar_id: string | null }>(
        "/api/onboard/detect-todoist-sync",
        token,
      );
      setSyncDetected(result.detected);
    } catch {
      // Detection is best-effort — silent failure is fine. Worst case we
      // don't surface the warning; HowToGuide still tells users to check.
      setSyncDetected(false);
    } finally {
      setSyncCheckLoading(false);
    }
  }, [supabase]);

  // Run detection once we know the user is connected to both Google and Todoist.
  // Todoist sync is irrelevant until both are present.
  useEffect(() => {
    if (gcalConnected && todoistConnected && syncDetected === null && !syncCheckLoading) {
      void runSyncDetection();
    }
  }, [gcalConnected, todoistConnected, syncDetected, syncCheckLoading, runSyncDetection]);

  const handleRecheck = useCallback(async () => {
    setSyncRecheckedAtLeastOnce(true);
    await runSyncDetection();
  }, [runSyncDetection]);

  const handleConnectGoogle = async () => {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return;
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001"}/auth/google?token=${token}`;
  };

  const handleConnectTodoist = async () => {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
    window.location.href = `${apiUrl}/auth/todoist?token=${token}`;
  };

  const canContinue = gcalConnected && todoistConnected;

  const handleContinue = async () => {
    if (!canContinue) return;
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    onAdvance(timezone, []);
  };

  const FADE = {
    hidden: { opacity: 0, y: 16 },
    show: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        delay: i * 0.08,
        type: "spring" as const,
        stiffness: 100,
        damping: 14,
      },
    }),
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{ background: "var(--bg)" }}
    >
      <motion.div
        initial="hidden"
        animate="show"
        className="w-full max-w-sm sm:max-w-md space-y-4"
      >
        <motion.div custom={0} variants={FADE} className="text-center mb-4">
          <h1
            className="font-display"
            style={{
              fontSize: "clamp(1.8rem, 4vw, 2.4rem)",
              letterSpacing: "-0.025em",
              color: "var(--text)",
            }}
          >
            Connect your tools
          </h1>
          <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 6 }}>
            Papyrus needs access to your calendar and tasks.
          </p>
        </motion.div>

        {/* Google Calendar */}
        <motion.div custom={1} variants={FADE} style={CARD}>
          <div className="flex items-start gap-3">
            <div
              style={{
                background: "var(--accent-tint)",
                padding: 8,
                borderRadius: 8,
              }}
            >
              <CalendarDays size={18} color="var(--accent)" />
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ color: "var(--text)", fontSize: 13, fontWeight: 500 }}>
                Google Calendar
              </p>
              <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 2 }}>
                Required — Papyrus reads and writes your events.
              </p>
              <div style={{ marginTop: 10 }}>
                {checking ? (
                  <p style={{ color: "var(--text-faint)", fontSize: 12 }}>Checking…</p>
                ) : gcalConnected ? (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      color: "var(--accent)",
                      fontSize: 12,
                    }}
                  >
                    <CheckCircle2 size={13} /> Connected
                  </div>
                ) : (
                  <motion.button
                    onClick={handleConnectGoogle}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    style={{
                      background: "var(--accent)",
                      color: "var(--bg)",
                      border: "none",
                      borderRadius: 8,
                      padding: "6px 14px",
                      fontSize: 12,
                      fontWeight: 500,
                      cursor: "pointer",
                    }}
                  >
                    Connect Google Calendar
                  </motion.button>
                )}
              </div>
            </div>
          </div>
        </motion.div>

        {/* Todoist */}
        <motion.div custom={2} variants={FADE} style={CARD}>
          <div className="flex items-start gap-3">
            <div style={{ background: "var(--accent-tint)", padding: 8, borderRadius: 8 }}>
              <CheckSquare size={18} color="var(--accent)" />
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ color: "var(--text)", fontSize: 13, fontWeight: 500 }}>
                Todoist
              </p>
              <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 2 }}>
                Required — Papyrus reads your tasks and sets due times.
              </p>
              <div style={{ marginTop: 10 }}>
                {checking ? (
                  <p style={{ color: "var(--text-faint)", fontSize: 12 }}>Checking…</p>
                ) : todoistConnected ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--accent)", fontSize: 12 }}>
                    <CheckCircle2 size={13} /> Connected
                  </div>
                ) : (
                  <motion.button
                    onClick={handleConnectTodoist}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    style={{
                      background: "var(--accent)",
                      color: "var(--bg)",
                      border: "none",
                      borderRadius: 8,
                      padding: "6px 14px",
                      fontSize: 12,
                      fontWeight: 500,
                      cursor: "pointer",
                    }}
                  >
                    Connect Todoist
                  </motion.button>
                )}
              </div>
            </div>
          </div>
        </motion.div>

        {/* Todoist→GCal sync warning (non-blocking). See PRE-RELEASE.md #9. */}
        {syncDetected === true && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            style={{
              ...CARD,
              background: "var(--surface-raised)",
              borderColor: "#d4a55a",
            }}
          >
            <div className="flex items-start gap-3">
              <div style={{ background: "rgba(212, 165, 90, 0.15)", padding: 8, borderRadius: 8 }}>
                <AlertTriangle size={18} color="#d4a55a" />
              </div>
              <div style={{ flex: 1 }}>
                <p style={{ color: "var(--text)", fontSize: 13, fontWeight: 500 }}>
                  Todoist is mirroring tasks to your Calendar
                </p>
                <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 6, lineHeight: 1.5 }}>
                  Papyrus writes events to your calendar directly. Leaving Todoist's
                  Google Calendar integration on would duplicate every scheduled task.
                  Turn it off in Todoist before continuing.
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
                    Google Calendar can take ~60 seconds to reflect the change after
                    you toggle the integration off in Todoist.
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        )}

        <motion.div custom={3} variants={FADE}>
          <motion.button
            onClick={handleContinue}
            disabled={!canContinue}
            whileHover={canContinue ? { scale: 1.01 } : undefined}
            whileTap={canContinue ? { scale: 0.99 } : undefined}
            style={{
              width: "100%",
              padding: "12px 0",
              borderRadius: 12,
              background: canContinue ? "var(--accent)" : "var(--accent-tint)",
              color: canContinue ? "var(--bg)" : "var(--accent)",
              border: "none",
              fontSize: 14,
              fontWeight: 500,
              cursor: canContinue ? "pointer" : "not-allowed",
              boxShadow: "none",
            }}
          >
            Continue →
          </motion.button>
        </motion.div>
      </motion.div>
    </div>
  );
}
