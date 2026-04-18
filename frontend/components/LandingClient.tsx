// frontend/components/LandingClient.tsx
"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Sun, RefreshCw, BookOpen } from "lucide-react";
import InkWash from "./InkWash";

// ── Waitlist Form ─────────────────────────────────────────────────────────────

function WaitlistForm() {
  const [firstName, setFirstName] = useState("");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || status === "loading") return;
    setStatus("loading");
    setErrorMsg("");

    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, firstName: firstName.trim() }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setErrorMsg((data as { error?: string }).error ?? "Something went wrong. Try again.");
        setStatus("error");
        return;
      }

      setStatus("success");
    } catch {
      setErrorMsg("Something went wrong. Try again.");
      setStatus("error");
    }
  };

  if (status === "success") {
    return (
      <motion.p
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        style={{
          fontSize: 15,
          color: "var(--text-muted)",
          fontFamily: "var(--font-literata)",
          fontStyle: "italic",
        }}
      >
        You&apos;re on the list. We&apos;ll be in touch.
      </motion.p>
    );
  }

  const inputStyle: React.CSSProperties = {
    padding: "11px 16px",
    borderRadius: 8,
    border: "1px solid var(--border-strong)",
    background: "var(--bg)",
    color: "var(--text)",
    fontSize: 14,
    fontFamily: "var(--font-literata)",
    outline: "none",
    transition: "border-color 0.15s",
    width: "100%",
  };

  return (
    <div style={{ width: "100%" }}>
      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", gap: 8, alignItems: "stretch" }}
      >
        <input
          type="text"
          placeholder="First name"
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
          style={{ ...inputStyle, flex: "0 0 130px" }}
          onFocus={(e) => ((e.currentTarget as HTMLInputElement).style.borderColor = "var(--accent)")}
          onBlur={(e) => ((e.currentTarget as HTMLInputElement).style.borderColor = "var(--border-strong)")}
        />
        <input
          type="email"
          placeholder="Email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={{ ...inputStyle, flex: "1 1 0" }}
          onFocus={(e) => ((e.currentTarget as HTMLInputElement).style.borderColor = "var(--accent)")}
          onBlur={(e) => ((e.currentTarget as HTMLInputElement).style.borderColor = "var(--border-strong)")}
        />
        <button
          type="submit"
          disabled={status === "loading"}
          style={{
            flex: "0 0 auto",
            padding: "11px 24px",
            borderRadius: 8,
            background: "var(--accent)",
            color: "var(--bg)",
            fontSize: 14,
            border: "none",
            cursor: status === "loading" ? "default" : "pointer",
            fontFamily: "var(--font-literata)",
            opacity: status === "loading" ? 0.7 : 1,
            transition: "background 0.15s, opacity 0.15s",
            whiteSpace: "nowrap",
          }}
          onMouseEnter={(e) => {
            if (status !== "loading")
              (e.currentTarget as HTMLElement).style.background = "var(--accent-hover)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "var(--accent)";
          }}
        >
          {status === "loading" ? "Joining…" : "Join the waitlist"}
        </button>
      </form>
      <p
        style={{
          marginTop: 10,
          fontSize: 12,
          color: status === "error" ? "var(--danger)" : "var(--text-faint)",
          fontFamily: "var(--font-literata)",
        }}
      >
        {status === "error" ? errorMsg : "No spam. Just early access when it\u2019s ready."}
      </p>
    </div>
  );
}

// ── Navigation ────────────────────────────────────────────────────────────────

function Nav() {
  const scrollToWaitlist = () => {
    document.getElementById("waitlist")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <nav
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 32px",
        background: "var(--bg)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span
        className="font-display"
        style={{ fontSize: 20, color: "var(--text)", letterSpacing: "-0.01em" }}
      >
        Papyrus
      </span>
      <button
        onClick={scrollToWaitlist}
        style={{
          fontSize: 13,
          color: "var(--text-muted)",
          background: "none",
          border: "1px solid var(--border-strong)",
          borderRadius: 8,
          padding: "6px 16px",
          cursor: "pointer",
          fontFamily: "var(--font-literata)",
          transition: "color 0.15s, border-color 0.15s",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.color = "var(--text)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--accent)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)";
        }}
      >
        Join the waitlist
      </button>
    </nav>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────

function Hero() {
  const scrollToWaitlist = () => {
    document.getElementById("waitlist")?.scrollIntoView({ behavior: "smooth" });
  };
  const scrollToHowItWorks = () => {
    document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <section
      style={{
        position: "relative",
        height: "100vh",
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        background: "var(--bg)",
      }}
    >
      <InkWash />

      <div
        style={{
          position: "relative",
          zIndex: 10,
          maxWidth: 680,
          padding: "0 48px",
        }}
      >
        <motion.h1
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          className="font-display"
          style={{
            fontSize: "clamp(2.5rem, 6vw, 5rem)",
            lineHeight: 1.1,
            letterSpacing: "-0.02em",
            color: "var(--text)",
            margin: 0,
          }}
        >
          Your to-do list and your calendar don&apos;t talk to each other.
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
          style={{
            marginTop: 24,
            maxWidth: "52ch",
            color: "var(--text-muted)",
            fontSize: "clamp(1rem, 2vw, 1.1rem)",
            lineHeight: 1.65,
          }}
        >
          Papyrus is the conversation. Describe your day, and it builds a
          schedule around your real day, not your ideal one.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
          style={{ marginTop: 36, display: "flex", gap: 12, flexWrap: "wrap" }}
        >
          <button
            onClick={scrollToWaitlist}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "11px 28px",
              borderRadius: 8,
              background: "var(--accent)",
              color: "var(--bg)",
              fontSize: 14,
              border: "none",
              cursor: "pointer",
              fontFamily: "var(--font-literata)",
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLElement).style.background = "var(--accent-hover)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLElement).style.background = "var(--accent)")
            }
          >
            Join the waitlist
          </button>
          <button
            onClick={scrollToHowItWorks}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "11px 28px",
              borderRadius: 8,
              background: "transparent",
              color: "var(--text-muted)",
              border: "1px solid var(--border-strong)",
              fontSize: 14,
              cursor: "pointer",
              fontFamily: "var(--font-literata)",
              transition: "color 0.15s, border-color 0.15s",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.color = "var(--text)";
              (e.currentTarget as HTMLElement).style.borderColor = "var(--accent)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
              (e.currentTarget as HTMLElement).style.borderColor = "var(--border-strong)";
            }}
          >
            See how it works
          </button>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.35 }}
        transition={{ delay: 1.2, duration: 0.6 }}
        style={{
          position: "absolute",
          bottom: 32,
          left: "50%",
          transform: "translateX(-50%)",
        }}
      >
        <div
          style={{
            width: 1,
            height: 32,
            background: "var(--text-muted)",
            animation: "pulse 2s ease-in-out infinite",
          }}
        />
      </motion.div>
    </section>
  );
}

// ── A day with Papyrus ────────────────────────────────────────────────────────

const STEPS = [
  {
    Icon: Sun,
    time: "Morning",
    title: "Start with intention, not anxiety",
    body: "Tell Papyrus how your day looks. It reads your tasks and calendar and proposes a time-blocked schedule. You confirm it. Then you start.",
  },
  {
    Icon: RefreshCw,
    time: "Mid-day",
    title: "When things slip, adapt. Not spiral.",
    body: "Mark what's done, decide what moves, get a revised afternoon in seconds. The goal was never a perfect plan. It was a day that bends without breaking.",
  },
  {
    Icon: BookOpen,
    time: "End of day",
    title: "See what you actually built",
    body: "Not what you planned. What you did. A short reflection that compounds over time: your patterns, your capacity, the wins that are easy to miss.",
  },
];

function ADayWithPapyrus() {
  return (
    <section
      id="how-it-works"
      style={{ padding: "96px 48px", background: "var(--surface)" }}
    >
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          viewport={{ once: true }}
          style={{
            textAlign: "center",
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--accent)",
            marginBottom: 16,
          }}
        >
          A day with Papyrus
        </motion.p>

        <motion.h2
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.05 }}
          viewport={{ once: true }}
          className="font-display"
          style={{
            fontSize: "clamp(1.75rem, 4vw, 2.5rem)",
            letterSpacing: "-0.02em",
            textAlign: "center",
            color: "var(--text)",
            marginBottom: 64,
          }}
        >
          Plan it. Adapt it. Learn from it.
        </motion.h2>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 24,
          }}
        >
          {STEPS.map(({ Icon, time, title, body }, i) => (
            <motion.div
              key={title}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: i * 0.1 }}
              viewport={{ once: true }}
              style={{
                position: "relative",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                padding: "28px 24px",
              }}
            >
              <p
                style={{
                  fontSize: 10,
                  fontWeight: 500,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "var(--accent)",
                  marginBottom: 14,
                }}
              >
                {time}
              </p>
              <Icon
                size={20}
                strokeWidth={1.5}
                style={{ color: "var(--accent)", marginBottom: 16 }}
              />
              <h3
                className="font-display"
                style={{
                  fontSize: 18,
                  color: "var(--text)",
                  marginBottom: 10,
                  letterSpacing: "-0.01em",
                }}
              >
                {title}
              </h3>
              <p
                style={{
                  fontSize: 14,
                  lineHeight: 1.65,
                  color: "var(--text-muted)",
                  maxWidth: "48ch",
                }}
              >
                {body}
              </p>
              <span
                className="font-display"
                style={{
                  position: "absolute",
                  top: 20,
                  right: 20,
                  fontSize: 56,
                  lineHeight: 1,
                  color: "var(--border)",
                  userSelect: "none",
                  pointerEvents: "none",
                }}
              >
                {i + 1}
              </span>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── CTA strip ─────────────────────────────────────────────────────────────────

function CTAStrip() {
  return (
    <section
      id="waitlist"
      style={{
        padding: "96px 48px",
        background: "var(--bg)",
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7 }}
        viewport={{ once: true }}
        style={{ maxWidth: 560, margin: "0 auto" }}
      >
        <h2
          className="font-display"
          style={{
            fontSize: "clamp(1.75rem, 4vw, 2.25rem)",
            letterSpacing: "-0.02em",
            color: "var(--text)",
            marginBottom: 32,
          }}
        >
          Your day is already complicated.
          <br />
          Planning it shouldn&apos;t be.
        </h2>
        <WaitlistForm />
      </motion.div>
    </section>
  );
}

// ── Root export ───────────────────────────────────────────────────────────────

export default function LandingClient() {
  return (
    <main style={{ display: "flex", flexDirection: "column" }}>
      <Nav />
      <Hero />
      <ADayWithPapyrus />
      <CTAStrip />
    </main>
  );
}
