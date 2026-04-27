import { notFound } from "next/navigation";
import fs from "fs";
import path from "path";
import Link from "next/link";

interface NudgeCatalogEntry {
  nudge_id: string;
  category: string;
  research: {
    primary_citation: string;
    supporting_citation?: string;
    behavior_change: string;
  };
  coach_message_template: string;
  learn_more_path: string;
}

function loadCatalog(): NudgeCatalogEntry[] {
  const catalogPath = path.join(process.cwd(), "..", "nudge_catalog.json");
  try {
    const raw = fs.readFileSync(catalogPath, "utf-8");
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

function nudgeIdFromSlug(slug: string): string {
  return slug.replace(/-/g, "_");
}

function humanTitle(nudgeId: string): string {
  const titles: Record<string, string> = {
    repeated_deferral:   "Why we keep pushing the same tasks",
    no_deadline:         "Why deadlines change the math on motivation",
    over_scheduling:     "Why we always plan too much",
    habit_skipped:       "Why the first 30 days of a habit are the hardest",
    waiting_task_stale:  "Why open loops drain your attention",
    backlog_growing:     "Why backlogs accelerate once they feel unmanageable",
    context_switching:   "Why switching tasks costs more than you think",
    deep_work_timing:    "Why creative work may be better at your low-energy times",
    no_breaks_scheduled: "Why skipping breaks compounds across the day",
    good_estimation:     "Why accurate time estimation is a trainable skill",
    completion_streak:   "Why consistent progress is the strongest motivator known",
  };
  return titles[nudgeId] ?? nudgeId.replace(/_/g, " ");
}

interface Props {
  params: Promise<{ nudgeType: string }>;
}

export default async function LearnPage({ params }: Props) {
  const { nudgeType } = await params;
  const nudgeId = nudgeIdFromSlug(nudgeType);
  const catalog = loadCatalog();
  const entry = catalog.find((n) => n.nudge_id === nudgeId);

  if (!entry) {
    notFound();
  }

  const title = humanTitle(nudgeId);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        color: "var(--text)",
        fontFamily: "var(--font-literata), Georgia, serif",
        padding: "64px 24px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <article style={{ maxWidth: "58ch", width: "100%" }}>

        <Link
          href="/today"
          style={{
            fontSize: 13,
            color: "var(--text-faint)",
            textDecoration: "none",
            display: "inline-block",
            marginBottom: 40,
            padding: "8px 0",
            letterSpacing: "0.04em",
          }}
        >
          ← Back to today
        </Link>

        <p
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--accent)",
            marginBottom: 12,
          }}
        >
          {entry.category === "positive" ? "Insight" : "Coaching science"}
        </p>

        <h1
          style={{
            fontSize: "clamp(22px, 5.2vw, 26px)",
            fontWeight: 400,
            lineHeight: 1.3,
            letterSpacing: "-0.02em",
            color: "var(--text)",
            marginBottom: 36,
          }}
        >
          {title}
        </h1>

        <section style={{ marginBottom: 28 }}>
          <h2
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--text-faint)",
              marginBottom: 12,
            }}
          >
            The research
          </h2>
          <p
            style={{
              fontSize: 14,
              lineHeight: 1.85,
              color: "var(--text-muted)",
              fontStyle: "italic",
            }}
          >
            {entry.research.primary_citation}
          </p>
        </section>

        {entry.research.supporting_citation && (
          <section style={{ marginBottom: 28 }}>
            <h2
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--text-faint)",
                marginBottom: 12,
              }}
            >
              Supporting evidence
            </h2>
            <p
              style={{
                fontSize: 14,
                lineHeight: 1.85,
                color: "var(--text-muted)",
                fontStyle: "italic",
              }}
            >
              {entry.research.supporting_citation}
            </p>
          </section>
        )}

        <div
          style={{
            height: 1,
            background: "var(--border)",
            margin: "32px 0",
          }}
        />

        <section style={{ marginBottom: 48 }}>
          <h2
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--text-faint)",
              marginBottom: 12,
            }}
          >
            What actually helps
          </h2>
          <p
            style={{
              fontSize: 14,
              lineHeight: 1.85,
              color: "var(--text)",
            }}
          >
            {entry.research.behavior_change}
          </p>
        </section>

        <Link
          href="/today"
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "12px 22px",
            minHeight: 44,
            background: "var(--accent)",
            color: "var(--bg)",
            borderRadius: 9,
            fontSize: 14,
            textDecoration: "none",
            letterSpacing: "0.01em",
          }}
        >
          Plan today →
        </Link>

      </article>
    </div>
  );
}

export async function generateMetadata({ params }: Props) {
  const { nudgeType } = await params;
  const nudgeId = nudgeIdFromSlug(nudgeType);
  const title = humanTitle(nudgeId);
  return {
    title: `${title} — Papyrus`,
  };
}
