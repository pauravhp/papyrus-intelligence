import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function WaitlistPendingPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string }>;
}) {
  const params = await searchParams;
  const email = params.email ?? "";

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
          padding: "40px 36px",
        }}
      >
        <h1
          className="font-display"
          style={{
            fontSize: 28,
            color: "var(--text)",
            marginBottom: 12,
            fontWeight: 400,
            letterSpacing: "-0.01em",
          }}
        >
          You&apos;re on the waitlist
        </h1>

        <p
          style={{
            fontSize: 14,
            color: "var(--text-muted)",
            marginBottom: 20,
            fontFamily: "var(--font-literata)",
            lineHeight: 1.6,
          }}
        >
          Papyrus is in private beta. {email ? (
            <>
              We&apos;ve added <strong style={{ color: "var(--text)" }}>{email}</strong> to the waitlist —
              we&apos;ll email you when seats open up.
            </>
          ) : (
            <>We&apos;ve added you to the waitlist — we&apos;ll email you when seats open up.</>
          )}
        </p>

        <p
          style={{
            fontSize: 13,
            color: "var(--text-faint)",
            fontStyle: "italic",
            marginBottom: 28,
            fontFamily: "var(--font-literata)",
            lineHeight: 1.7,
          }}
        >
          In the meantime: Papyrus is a calm scheduling coach that plans your day,
          respects your energy, and adapts gracefully when things slip.
        </p>

        <Link
          href="/"
          style={{
            display: "inline-block",
            padding: "10px 18px",
            background: "var(--accent)",
            color: "#fff",
            borderRadius: 9,
            fontSize: 13,
            fontFamily: "var(--font-literata)",
            textDecoration: "none",
          }}
        >
          Back to home
        </Link>
      </div>
    </div>
  );
}
