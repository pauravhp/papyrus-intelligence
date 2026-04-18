import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { createClient } from "@/utils/supabase/server";
import AdminDashboard from "./AdminDashboard";

interface HogQLResult {
  results: (string | number | null)[][];
}

async function hogql(query: string): Promise<(string | number | null)[][]> {
  const res = await fetch(
    `https://us.posthog.com/api/projects/${process.env.POSTHOG_PROJECT_ID}/query`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.POSTHOG_PERSONAL_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ query: { kind: "HogQLQuery", query } }),
      cache: "no-store",
    }
  );
  if (!res.ok) return [];
  const data: HogQLResult = await res.json();
  return data.results ?? [];
}

export default async function AdminPage() {
  const cookieStore = await cookies();
  const supabase = createClient(cookieStore);
  const { data } = await supabase.auth.getUser();

  if (!data?.user || data.user.id !== process.env.ADMIN_USER_ID) {
    notFound();
  }

  const [
    schedulesResult,
    tasksResult,
    minutesResult,
    tasksCompletedResult,
    onboardedResult,
    scheduledUsersResult,
    reviewedUsersResult,
    rhythmUsersResult,
    replanUsersResult,
    reviewAdoptionResult,
    activityResult,
    feedbackResult,
  ] = await Promise.all([
    hogql("SELECT count() FROM events WHERE event = 'schedule_confirmed'"),
    hogql("SELECT sum(toInt64OrNull(properties.task_count)) FROM events WHERE event = 'schedule_confirmed'"),
    hogql("SELECT sum(toInt64OrNull(properties.total_duration_minutes)) FROM events WHERE event = 'schedule_confirmed'"),
    hogql("SELECT sum(toInt64OrNull(properties.tasks_completed)) FROM events WHERE event = 'review_submitted'"),
    hogql("SELECT count(DISTINCT distinct_id) FROM events WHERE event = 'onboarding_completed'"),
    hogql("SELECT count(DISTINCT distinct_id) FROM events WHERE event = 'schedule_confirmed'"),
    hogql("SELECT count(DISTINCT distinct_id) FROM events WHERE event = 'review_submitted'"),
    hogql("SELECT count(DISTINCT distinct_id) FROM events WHERE event = 'rhythm_created'"),
    hogql("SELECT count(DISTINCT distinct_id) FROM events WHERE event = 'replan_confirmed'"),
    hogql("SELECT count(DISTINCT distinct_id) FROM events WHERE event = 'review_submitted'"),
    hogql(`
      SELECT toDate(timestamp) as day, count() as schedules
      FROM events
      WHERE event = 'schedule_confirmed'
        AND timestamp >= now() - INTERVAL 30 DAY
      GROUP BY day
      ORDER BY day ASC
    `),
    hogql(`
      SELECT
        toInt64OrNull(properties.nps_score) as nps,
        properties.message as message,
        toDate(timestamp) as submitted_on
      FROM events
      WHERE event = 'feedback_submitted'
      ORDER BY timestamp DESC
      LIMIT 8
    `),
  ]);

  const stats = {
    schedules: Number(schedulesResult[0]?.[0] ?? 0),
    tasks: Number(tasksResult[0]?.[0] ?? 0),
    hours: Math.round(Number(minutesResult[0]?.[0] ?? 0) / 60),
    tasksCompleted: Number(tasksCompletedResult[0]?.[0] ?? 0),
  };

  const onboardedCount = Number(onboardedResult[0]?.[0] ?? 0);
  const funnel = {
    onboarded: onboardedCount,
    scheduled: Number(scheduledUsersResult[0]?.[0] ?? 0),
    reviewed: Number(reviewedUsersResult[0]?.[0] ?? 0),
  };

  const adoption = {
    review: { users: Number(reviewAdoptionResult[0]?.[0] ?? 0), total: onboardedCount },
    rhythms: { users: Number(rhythmUsersResult[0]?.[0] ?? 0), total: onboardedCount },
    replan: { users: Number(replanUsersResult[0]?.[0] ?? 0), total: onboardedCount },
  };

  const activity = activityResult.map(([day, count]) => ({
    day: String(day),
    count: Number(count),
  }));

  const feedback = feedbackResult.map(([nps, message, submittedOn]) => ({
    nps: nps !== null ? Number(nps) : null,
    message: message ? String(message) : null,
    submittedOn: String(submittedOn),
  }));

  const npsResponses = feedback.filter((f) => f.nps !== null);
  const promoters = npsResponses.filter((f) => f.nps! >= 9).length;
  const detractors = npsResponses.filter((f) => f.nps! <= 6).length;
  const npsScore =
    npsResponses.length > 0
      ? Math.round(((promoters - detractors) / npsResponses.length) * 100)
      : null;

  return (
    <AdminDashboard
      stats={stats}
      funnel={funnel}
      adoption={adoption}
      activity={activity}
      feedback={feedback}
      npsScore={npsScore}
      npsBreakdown={{
        promoters,
        passives: npsResponses.length - promoters - detractors,
        detractors,
        total: npsResponses.length,
      }}
    />
  );
}
