"use client";

interface Stats {
  schedules: number;
  tasks: number;
  hours: number;
  tasksCompleted: number;
}

interface Funnel {
  onboarded: number;
  scheduled: number;
  reviewed: number;
}

interface AdoptionMetric {
  users: number;
  total: number;
}

interface Adoption {
  review: AdoptionMetric;
  rhythms: AdoptionMetric;
  replan: AdoptionMetric;
}

interface ActivityPoint {
  day: string;
  count: number;
}

interface FeedbackEntry {
  nps: number | null;
  message: string | null;
  submittedOn: string;
}

interface NpsBreakdown {
  promoters: number;
  passives: number;
  detractors: number;
  total: number;
}

interface Props {
  stats: Stats;
  funnel: Funnel;
  adoption: Adoption;
  activity: ActivityPoint[];
  feedback: FeedbackEntry[];
  npsScore: number | null;
  npsBreakdown: NpsBreakdown;
}

const DAYS = ["S", "M", "T", "W", "T", "F", "S"];

function pct(part: number, total: number) {
  if (total === 0) return 0;
  return Math.round((part / total) * 100);
}

export default function AdminDashboard({
  stats, funnel, adoption, activity, feedback, npsScore, npsBreakdown,
}: Props) {
  const maxActivity = Math.max(...activity.map((a) => a.count), 1);

  return (
    <div style={{ padding: "48px", background: "var(--bg)", minHeight: "100vh", color: "var(--text)", fontFamily: "var(--font-literata)" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 48, paddingBottom: 24, borderBottom: "1px solid var(--border)" }}>
        <div>
          <h1 className="font-display" style={{ fontSize: 28, letterSpacing: "-0.02em", marginBottom: 4 }}>Papyrus</h1>
          <p style={{ fontSize: 12, color: "var(--text-faint)", fontStyle: "italic" }}>Usage · internal view</p>
        </div>
        <span style={{ fontSize: 11, color: "var(--text-faint)", fontStyle: "italic" }}>Live data from PostHog</span>
      </div>

      {/* Aggregate stats */}
      <p style={{ fontSize: 10, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--text-faint)", marginBottom: 16 }}>All time</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 48 }}>
        {[
          { value: stats.schedules.toLocaleString(), label: "Schedules confirmed" },
          { value: stats.tasks.toLocaleString(), label: "Tasks placed by Papyrus" },
          { value: stats.hours.toLocaleString(), label: "Hours of focus scheduled" },
          { value: stats.tasksCompleted.toLocaleString(), label: "Tasks completed via review" },
        ].map(({ value, label }) => (
          <div key={label} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: "24px 24px 20px" }}>
            <div className="font-display" style={{ fontSize: 36, letterSpacing: "-0.03em", lineHeight: 1, marginBottom: 6 }}>{value}</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", fontStyle: "italic" }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Funnel + Adoption */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 48 }}>

        {/* Funnel */}
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: 28 }}>
          <div className="font-display" style={{ fontSize: 15, marginBottom: 24 }}>Activation funnel</div>
          {[
            { label: "Onboarding completed", count: funnel.onboarded, width: 100 },
            { label: "First schedule confirmed", count: funnel.scheduled, width: pct(funnel.scheduled, funnel.onboarded) },
            { label: "First review submitted", count: funnel.reviewed, width: pct(funnel.reviewed, funnel.onboarded) },
          ].map(({ label, count, width }, i) => (
            <div key={label}>
              {i > 0 && (
                <>
                  <div style={{ width: 2, height: 8, background: "var(--border-strong)", margin: "0 0 0 14px", borderRadius: 1 }} />
                  <p style={{ fontSize: 10, color: "var(--text-faint)", fontStyle: "italic", marginLeft: 14, marginBottom: 4 }}>
                    {pct(count, funnel.onboarded)}% reached this step
                  </p>
                </>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: i < 2 ? 0 : undefined }}>
                <div style={{ flex: 1, height: 28, background: "var(--surface-raised)", borderRadius: 6, overflow: "hidden" }}>
                  <div style={{
                    width: `${width}%`, height: "100%",
                    background: i === 0 ? "rgba(196,130,26,0.22)" : "rgba(196,130,26,0.10)",
                    borderRadius: 6, display: "flex", alignItems: "center", paddingLeft: 10,
                  }}>
                    <span style={{ fontSize: 12, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{label}</span>
                  </div>
                </div>
                <span style={{ fontSize: 11, color: "var(--text-muted)", width: 40, textAlign: "right" }}>{count}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Adoption */}
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: 28 }}>
          <div className="font-display" style={{ fontSize: 15, marginBottom: 24 }}>Feature adoption</div>
          {[
            { name: "End-of-day review", metric: adoption.review },
            { name: "Rhythms", metric: adoption.rhythms },
            { name: "Mid-day replan", metric: adoption.replan },
          ].map(({ name, metric }) => {
            const p = pct(metric.users, metric.total);
            return (
              <div key={name} style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 13 }}>{name}</span>
                  <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{p}%</span>
                </div>
                <div style={{ height: 6, background: "var(--surface-raised)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${p}%`, height: "100%", background: "var(--accent)", borderRadius: 3, opacity: 0.6 }} />
                </div>
                <p style={{ fontSize: 11, color: "var(--text-faint)", fontStyle: "italic", marginTop: 4 }}>
                  {metric.users} of {metric.total} users
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Activity chart */}
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: "28px 28px 20px", marginBottom: 48 }}>
        <div className="font-display" style={{ fontSize: 15, marginBottom: 24 }}>Schedules confirmed — last 30 days</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 80 }}>
          {activity.map((point) => (
            <div key={point.day} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, height: "100%", justifyContent: "flex-end" }}>
              <div
                title={`${point.count} schedule${point.count !== 1 ? "s" : ""}`}
                style={{
                  width: "100%",
                  height: `${Math.max(4, (point.count / maxActivity) * 72)}px`,
                  background: "var(--accent)",
                  borderRadius: "3px 3px 0 0",
                  opacity: 0.55,
                  minHeight: 3,
                }}
              />
              <span style={{ fontSize: 9, color: "var(--text-faint)", letterSpacing: "0.04em" }}>
                {DAYS[new Date(point.day).getDay()]}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* NPS + feedback */}
      <p style={{ fontSize: 10, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--text-faint)", marginBottom: 16 }}>User feedback</p>
      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 24 }}>

        {/* NPS */}
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: 28, textAlign: "center" }}>
          <p style={{ fontSize: 10, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--text-faint)", marginBottom: 0 }}>Net Promoter Score</p>
          <div className="font-display" style={{ fontSize: 64, letterSpacing: "-0.05em", color: "var(--accent)", lineHeight: 1, margin: "16px 0 6px" }}>
            {npsScore !== null ? npsScore : "—"}
          </div>
          <p style={{ fontSize: 11, color: "var(--text-muted)", fontStyle: "italic", marginBottom: 20 }}>
            from {npsBreakdown.total} responses
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", fontSize: 11, color: "var(--text-faint)" }}>
            {[
              { val: npsBreakdown.promoters, label: "Promoters", color: "#5a8a5a" },
              { val: npsBreakdown.passives,  label: "Passive",   color: "var(--text-muted)" },
              { val: npsBreakdown.detractors, label: "Detractors", color: "var(--text-faint)" },
            ].map(({ val, label, color }) => (
              <div key={label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
                <span style={{ fontSize: 14, color }}>{val}</span>
                <span>{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Responses */}
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: 28 }}>
          <div className="font-display" style={{ fontSize: 15, marginBottom: 20 }}>Recent feedback</div>
          {feedback.filter((f) => f.message).length === 0 ? (
            <p style={{ color: "var(--text-faint)", fontStyle: "italic", fontSize: 13 }}>No written feedback yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {feedback.filter((f) => f.message).map((f, i) => (
                <div key={i} style={{ padding: "14px 16px", background: "var(--surface-raised)", borderRadius: 8 }}>
                  <p style={{ fontSize: 13, fontStyle: "italic", color: "var(--text)", lineHeight: 1.55, marginBottom: 8 }}>
                    &quot;{f.message}&quot;
                  </p>
                  <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--text-faint)" }}>
                    {f.nps !== null && <span>NPS {f.nps}</span>}
                    <span>{f.submittedOn}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
