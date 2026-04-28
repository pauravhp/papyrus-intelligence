"use client";

import { useEffect, useMemo, useState } from "react";
import { apiPatch } from "@/utils/api";

interface TimezoneTabProps {
  config: Record<string, unknown>;
  getToken: () => Promise<string>;
}

const LABEL: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--text-muted)",
  marginBottom: 5,
};

const INPUT: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  color: "var(--text)",
  borderRadius: 8,
  padding: "9px 11px",
  fontSize: 13,
  fontFamily: "var(--font-literata)",
  outline: "none",
  width: "100%",
  WebkitAppearance: "none",
};

const GROUP_LABEL: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: "var(--text-faint)",
  paddingBottom: 10,
  marginBottom: 16,
  borderBottom: "1px solid var(--border)",
};

// Sensible fallback list when Intl.supportedValuesOf("timeZone") is unavailable.
const FALLBACK_ZONES = [
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Toronto",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Dublin",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Madrid",
  "Europe/Athens",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Bangkok",
  "Asia/Singapore",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
  "UTC",
];

function getAllZones(): string[] {
  // Modern Chromium / Safari / Firefox expose this. Older runtimes don't.
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  if (typeof intl.supportedValuesOf === "function") {
    try {
      return intl.supportedValuesOf("timeZone");
    } catch {
      /* fall through */
    }
  }
  return FALLBACK_ZONES;
}

export default function TimezoneTab({ config, getToken }: TimezoneTabProps) {
  const userBlock = (config.user ?? {}) as Record<string, unknown>;
  const initialStored = (userBlock.timezone as string) ?? "";

  const detected = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch {
      return "";
    }
  }, []);

  const [stored, setStored] = useState<string>(initialStored);
  const [draft, setDraft] = useState<string>(initialStored || detected || "UTC");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allZones = useMemo(() => {
    const list = getAllZones();
    // Make sure the detected/stored values are present even if the
    // browser's list is stale or doesn't include them for some reason.
    const set = new Set(list);
    if (detected) set.add(detected);
    if (stored) set.add(stored);
    return Array.from(set).sort();
  }, [detected, stored]);

  const dirty = draft !== stored;
  const detectedDiffersFromStored = !!detected && detected !== stored;

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 2000);
    return () => clearTimeout(t);
  }, [saved]);

  const handleSave = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      const token = await getToken();
      const result = await apiPatch<{ timezone: string }>(
        "/api/settings/timezone",
        { timezone: draft },
        token,
      );
      setStored(result.timezone);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 520 }}>
      <div style={{ marginBottom: 32 }}>
        <p style={GROUP_LABEL}>Timezone</p>
        <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.55, marginBottom: 18 }}>
          Papyrus reads and writes events in this timezone. Update it after travelling
          or moving so your schedule lines up with your day.
        </p>

        <div style={{ marginBottom: 18 }}>
          <label style={LABEL}>Stored timezone</label>
          <select
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            style={INPUT}
            aria-label="Timezone"
          >
            {allZones.map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
            padding: "10px 12px",
            background: "var(--surface-raised)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            marginBottom: 22,
          }}
        >
          <div style={{ flex: 1, minWidth: 180 }}>
            <p style={{ fontSize: 11, color: "var(--text-faint)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 3 }}>
              Detected from this browser
            </p>
            <p style={{ fontSize: 13, color: "var(--text)", fontFamily: "var(--font-literata)" }}>
              {detected || "(unavailable)"}
            </p>
          </div>
          {detectedDiffersFromStored && (
            <button
              type="button"
              onClick={() => setDraft(detected)}
              disabled={draft === detected}
              style={{
                padding: "8px 14px",
                background: "transparent",
                color: draft === detected ? "var(--text-faint)" : "var(--accent)",
                border: `1px solid ${draft === detected ? "var(--border)" : "var(--accent)"}`,
                borderRadius: 7,
                fontFamily: "var(--font-literata)",
                fontSize: 12,
                cursor: draft === detected ? "default" : "pointer",
              }}
            >
              {draft === detected ? "Selected" : "Use detected"}
            </button>
          )}
        </div>

        {error && (
          <p style={{ color: "var(--danger)", fontSize: 12, marginBottom: 12 }}>{error}</p>
        )}

        <button
          type="button"
          onClick={handleSave}
          disabled={!dirty || saving}
          style={{
            padding: "10px 22px",
            background: !dirty || saving ? "var(--accent-tint)" : "var(--accent)",
            color: !dirty || saving ? "var(--accent)" : "var(--bg)",
            border: "none",
            borderRadius: 9,
            fontFamily: "var(--font-literata)",
            fontSize: 13,
            fontWeight: 500,
            cursor: !dirty || saving ? "not-allowed" : "pointer",
            transition: "background 0.15s",
          }}
        >
          {saved ? "Saved" : saving ? "Saving…" : "Save timezone"}
        </button>
      </div>
    </div>
  );
}
