// frontend/components/CalendarSection.tsx
"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/utils/supabase/client";
import { apiFetch, apiPatch, ApiError } from "@/utils/api";

interface CalendarItem {
  id: string;
  summary: string;
  background_color: string;
  access_role: "owner" | "writer" | "reader" | "freeBusyReader";
}

const isWritable = (cal: CalendarItem) =>
  cal.access_role === "owner" || cal.access_role === "writer";

const isReadOnly = (cal: CalendarItem) =>
  cal.access_role === "reader" || cal.access_role === "freeBusyReader";

const LABEL: React.CSSProperties = {
  color: "var(--text-muted)",
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  marginBottom: 8,
  display: "block",
};

const CAL_ROW: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  borderRadius: 8,
  cursor: "pointer",
  transition: "background 0.12s",
  marginBottom: 2,
};

export default function CalendarSection({
  config,
  onConfigUpdate,
}: {
  config: Record<string, unknown>;
  onConfigUpdate: (patch: Record<string, unknown>) => void;
}) {
  const [calendars, setCalendars] = useState<CalendarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsReconnect, setNeedsReconnect] = useState(false);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [writeId, setWriteId] = useState<string>("primary");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      setNeedsReconnect(false);
      try {
        const supabase = createClient();
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token ?? "";
        const cals = await apiFetch<CalendarItem[]>("/api/calendars", token);
        if (!cancelled) {
          setCalendars(cals);
          // Initialise selection from config, defaulting to primary
          const cfgSources = (config.source_calendar_ids as string[] | undefined) ?? ["primary"];
          const cfgWrite = (config.write_calendar_id as string | undefined) ?? "primary";
          setSourceIds(cfgSources.length > 0 ? cfgSources : ["primary"]);
          setWriteId(cfgWrite);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.code === "google_reconnect_required") {
          setNeedsReconnect(true);
        } else {
          setError("Couldn't load your calendars.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleReconnect = async () => {
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token ?? "";
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    window.location.href = `${apiUrl}/auth/google?token=${token}&redirect_after=${encodeURIComponent("/dashboard/settings")}`;
  };

  const toggleSource = (id: string) => {
    setSourceIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSave = async () => {
    if (sourceIds.length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? "";
      await apiPatch("/api/settings/calendars", {
        source_calendar_ids: sourceIds,
        write_calendar_id: writeId,
      }, token);
      onConfigUpdate({ source_calendar_ids: sourceIds, write_calendar_id: writeId });
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div>
        <span style={LABEL}>Read from</span>
        {[0.6, 0.45, 0.3].map((opacity, i) => (
          <div key={i} style={{
            height: 34,
            background: "var(--surface-raised)",
            borderRadius: 8,
            marginBottom: 4,
            opacity,
            animation: "pulse 1.4s ease-in-out infinite",
          }} />
        ))}
      </div>
    );
  }

  if (needsReconnect) {
    return (
      <div>
        <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginBottom: 12 }}>
          Your Google Calendar connection has expired.<br />
          <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
            Reconnect to reload your calendars — your settings will stay intact.
          </span>
        </p>
        <button
          onClick={handleReconnect}
          style={{
            padding: "7px 14px",
            background: "transparent",
            color: "var(--accent)",
            border: "1px solid var(--accent)",
            borderRadius: 8,
            fontFamily: "var(--font-literata)",
            fontSize: 12,
            cursor: "pointer",
            transition: "all 0.15s",
          }}
        >
          Reconnect Google Calendar
        </button>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginBottom: 8 }}>
          {error}<br />
          <span style={{ fontSize: 12, color: "var(--text-faint)" }}>
            Check your Google connection and try again.
          </span>
        </p>
        <button
          onClick={() => window.location.reload()}
          style={{
            fontSize: 12,
            color: "var(--accent)",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontFamily: "var(--font-literata)",
            textDecoration: "underline",
            textDecorationStyle: "dotted",
          }}
        >
          Try again
        </button>
      </div>
    );
  }

  const writableCals = calendars.filter(isWritable);

  return (
    <div>
      {/* Read from */}
      <span style={LABEL}>Read from</span>
      <div style={{ marginBottom: 16 }}>
        {calendars.map((cal) => {
          const checked = sourceIds.includes(cal.id);
          const disabled = isReadOnly(cal);
          return (
            <div
              key={cal.id}
              onClick={() => !disabled && toggleSource(cal.id)}
              style={{
                ...CAL_ROW,
                background: checked && !disabled ? "var(--accent-tint)" : "transparent",
                opacity: disabled ? 0.5 : 1,
                cursor: disabled ? "default" : "pointer",
              }}
            >
              {/* Checkbox */}
              <div style={{
                width: 16, height: 16, borderRadius: 4, flexShrink: 0,
                border: `1.5px solid ${checked && !disabled ? "var(--accent)" : "var(--border-strong)"}`,
                background: checked && !disabled ? "var(--accent)" : "transparent",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {checked && !disabled && (
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
                    stroke="white" strokeWidth="2">
                    <polyline points="1.5,5 4,7.5 8.5,2.5"/>
                  </svg>
                )}
              </div>
              {/* Colour dot */}
              <span style={{
                width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
                background: cal.background_color,
              }} />
              {/* Name */}
              <span style={{ fontSize: 13, color: "var(--text)", flex: 1 }}>
                {cal.summary}
              </span>
              {/* Read-only badge */}
              {disabled && (
                <span style={{
                  fontSize: 10, color: "var(--text-faint)",
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  padding: "1px 5px",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase" as const,
                }}>
                  Read-only
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Write to */}
      <span style={LABEL}>Write to</span>
      <div style={{ marginBottom: 12 }}>
        {writableCals.map((cal) => {
          const selected = writeId === cal.id;
          return (
            <div
              key={cal.id}
              onClick={() => setWriteId(cal.id)}
              style={{
                ...CAL_ROW,
                background: selected ? "var(--accent-tint)" : "transparent",
              }}
            >
              {/* Radio */}
              <div style={{
                width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
                border: `1.5px solid ${selected ? "var(--accent)" : "var(--border-strong)"}`,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {selected && (
                  <div style={{
                    width: 8, height: 8, borderRadius: "50%",
                    background: "var(--accent)",
                  }} />
                )}
              </div>
              <span style={{
                width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
                background: cal.background_color,
              }} />
              <span style={{ fontSize: 13, color: "var(--text)", flex: 1 }}>
                {cal.summary}
              </span>
            </div>
          );
        })}
      </div>

      {saveError && (
        <p style={{ color: "var(--danger)", fontSize: 12, marginBottom: 8 }}>{saveError}</p>
      )}

      <button
        onClick={handleSave}
        disabled={saving || sourceIds.length === 0}
        style={{
          width: "100%",
          padding: "9px 0",
          borderRadius: 8,
          background: saving ? "var(--accent-tint)" : "var(--accent)",
          color: saving ? "var(--accent)" : "var(--bg)",
          border: "none",
          fontSize: 13,
          cursor: saving || sourceIds.length === 0 ? "not-allowed" : "pointer",
          fontFamily: "var(--font-literata)",
        }}
      >
        {saving ? "Saving…" : "Save calendar settings"}
      </button>
    </div>
  );
}
