import Link from "next/link";

export const dynamic = "force-dynamic";

const COPY: Record<string, { title: string; body: string }> = {
  partial_scope: {
    title: "We couldn’t finish connecting Google Calendar",
    body:
      "Google’s consent screen had some permissions unchecked. Papyrus needs every box ticked to read your events and write the schedule we propose. Try again with all boxes checked.",
  },
  token_exchange_failed: {
    title: "Something went wrong with Google’s sign-in",
    body:
      "We couldn’t exchange the sign-in code with Google. This is usually transient — try connecting again. If it keeps happening, send us a note.",
  },
};

const FALLBACK = {
  title: "We couldn’t finish connecting your account",
  body: "Try connecting again. If it keeps happening, send us a note.",
};

export default async function OAuthErrorPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  const params = await searchParams;
  const reason = params.reason ?? "";
  const { title, body } = COPY[reason] ?? FALLBACK;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
        padding: "0 16px",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 16,
          padding: "32px 24px",
        }}
      >
        <h1
          className="font-display"
          style={{
            fontSize: 24,
            color: "var(--text)",
            marginBottom: 12,
            fontWeight: 400,
            letterSpacing: "-0.01em",
            lineHeight: 1.25,
          }}
        >
          {title}
        </h1>

        <p
          style={{
            fontSize: 14,
            color: "var(--text-muted)",
            marginBottom: 28,
            fontFamily: "var(--font-literata)",
            lineHeight: 1.6,
          }}
        >
          {body}
        </p>

        <Link
          href="/dashboard/settings"
          style={{
            display: "inline-block",
            padding: "12px 20px",
            minHeight: 44,
            background: "var(--accent)",
            color: "#fff",
            borderRadius: 9,
            fontSize: 14,
            fontFamily: "var(--font-literata)",
            textDecoration: "none",
            marginRight: 10,
          }}
        >
          Try connecting again
        </Link>

        <Link
          href="/today"
          style={{
            display: "inline-block",
            padding: "12px 20px",
            minHeight: 44,
            color: "var(--text-muted)",
            borderRadius: 9,
            fontSize: 14,
            fontFamily: "var(--font-literata)",
            textDecoration: "none",
          }}
        >
          Back to Papyrus
        </Link>
      </div>
    </div>
  );
}
