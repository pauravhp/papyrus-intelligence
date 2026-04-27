// frontend/components/LandingClient.tsx
"use client";

import { motion } from "framer-motion";
import { Sun, RefreshCw, BookOpen } from "lucide-react";
import InkWash from "./InkWash";

// ── Shared CTA ────────────────────────────────────────────────────────────────

const CTA_PRIMARY: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "13px 28px",
  minHeight: 46,
  borderRadius: 8,
  background: "var(--accent)",
  color: "var(--bg)",
  fontSize: 14,
  border: "none",
  cursor: "pointer",
  fontFamily: "var(--font-literata)",
  textDecoration: "none",
  transition: "background 0.15s",
};

const CTA_SECONDARY: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "13px 28px",
  minHeight: 46,
  borderRadius: 8,
  background: "transparent",
  color: "var(--text-muted)",
  border: "1px solid var(--border-strong)",
  fontSize: 14,
  cursor: "pointer",
  fontFamily: "var(--font-literata)",
  textDecoration: "none",
  transition: "color 0.15s, border-color 0.15s",
};

// ── Navigation ────────────────────────────────────────────────────────────────

function Nav() {
  return (
    <nav
      className="landing-nav"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
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
      <a
        href="/login"
        style={{
          fontSize: 13,
          color: "var(--text-muted)",
          background: "none",
          border: "1px solid var(--border-strong)",
          borderRadius: 8,
          padding: "10px 16px",
          minHeight: 40,
          display: "inline-flex",
          alignItems: "center",
          cursor: "pointer",
          fontFamily: "var(--font-literata)",
          textDecoration: "none",
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
        Get started
      </a>
    </nav>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────

function Hero() {
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
        className="landing-hero-inner"
        style={{
          position: "relative",
          zIndex: 10,
          maxWidth: 680,
          width: "100%",
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
          <a
            href="/login"
            style={CTA_PRIMARY}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLElement).style.background = "var(--accent-hover)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLElement).style.background = "var(--accent)")
            }
          >
            Get started
          </a>
          <button
            onClick={scrollToHowItWorks}
            style={CTA_SECONDARY}
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
    body: "A note like “running behind, skip the gym” is enough to reshape the rest of your day. Mark what’s done, decide what moves, and get a revised afternoon in seconds.",
  },
  {
    Icon: BookOpen,
    time: "End of day",
    title: "See what you actually built",
    body: "Not what you planned. What you did. A short reflection at day’s end — the wins, the shifts, what tomorrow inherits.",
  },
];

function ADayWithPapyrus() {
  return (
    <section
      id="how-it-works"
      className="landing-section"
      style={{ background: "var(--surface)" }}
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

// ── Why Papyrus (positioning) ─────────────────────────────────────────────────

function WhyPapyrus() {
  return (
    <section
      className="landing-section"
      style={{ background: "var(--bg)" }}
    >
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
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
          Why Papyrus
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
            marginBottom: 40,
          }}
        >
          Built for you, not your team.
        </motion.h2>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1 }}
          viewport={{ once: true }}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 22,
            color: "var(--text-secondary)",
            fontSize: "clamp(1rem, 1.6vw, 1.05rem)",
            lineHeight: 1.75,
            textAlign: "center",
          }}
        >
          <p style={{ margin: 0 }}>
            Most scheduling tools assume the problem is coordinating across people
            &mdash; defending blocks, finding meeting slots, optimising shared
            calendars. Papyrus is the opposite. It is built for the one person
            who has to actually do the work: you, alone with your task list at
            9am, trying to figure out what kind of day this is going to be.
          </p>
          <p style={{ margin: 0 }}>
            The point is not a perfect schedule. It is understanding what you
            actually do, on the days you do it well &mdash; and getting better
            at choosing.
          </p>
        </motion.div>
      </div>
    </section>
  );
}

// ── CTA strip ─────────────────────────────────────────────────────────────────

function CTAStrip() {
  return (
    <section
      className="landing-section"
      style={{ background: "var(--surface)" }}
    >
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7 }}
        viewport={{ once: true }}
        style={{
          maxWidth: 560,
          margin: "0 auto",
          textAlign: "center",
        }}
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
        <a
          href="/login"
          style={CTA_PRIMARY}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLElement).style.background = "var(--accent-hover)")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLElement).style.background = "var(--accent)")
          }
        >
          Get started
        </a>
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
      <WhyPapyrus />
      <CTAStrip />
    </main>
  );
}
