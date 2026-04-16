// frontend/components/LandingClient.tsx
"use client";

import { motion } from "framer-motion";
import { ScanLine, CalendarCheck, MessageSquare } from "lucide-react";
import InkWash from "./InkWash";

// ── Navigation ──────────────────────────────────────────────────────────────

function Nav() {
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
      <a
        href="https://forms.gle/sSpeWWJFEp48qANE6"
        target="_blank"
        rel="noopener noreferrer"
        style={{
          fontSize: 13,
          color: "var(--text-muted)",
          textDecoration: "none",
          border: "1px solid var(--border-strong)",
          borderRadius: 8,
          padding: "6px 16px",
          transition: "color 0.15s, border-color 0.15s",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.color = "var(--text)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--accent)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
          (e.currentTarget as HTMLElement).style.borderColor =
            "var(--border-strong)";
        }}
      >
        Join the waitlist
      </a>
    </nav>
  );
}

// ── Hero ─────────────────────────────────────────────────────────────────────

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
          Your schedule,
          <br />
          finally intelligent.
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
          style={{
            marginTop: 24,
            maxWidth: "58ch",
            color: "var(--text-muted)",
            fontSize: "clamp(1rem, 2vw, 1.1rem)",
            lineHeight: 1.65,
          }}
        >
          A calm scheduling coach that plans your day, respects your energy,
          and adapts gracefully when things slip.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
          style={{ marginTop: 36, display: "flex", gap: 12, flexWrap: "wrap" }}
        >
          <a
            href="https://forms.gle/sSpeWWJFEp48qANE6"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "11px 28px",
              borderRadius: 8,
              background: "var(--accent)",
              color: "var(--bg)",
              fontSize: 14,
              textDecoration: "none",
              fontFamily: "var(--font-literata)",
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLElement).style.background =
                "var(--accent-hover)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLElement).style.background =
                "var(--accent)")
            }
          >
            Join the waitlist
          </a>
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
              (e.currentTarget as HTMLElement).style.borderColor =
                "var(--accent)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
              (e.currentTarget as HTMLElement).style.borderColor =
                "var(--border-strong)";
            }}
          >
            See how it works
          </button>
        </motion.div>
      </div>

      {/* Scroll indicator */}
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

// ── How it works ──────────────────────────────────────────────────────────────

const STEPS = [
  {
    icon: ScanLine,
    title: "Connect your calendar",
    body: "Link Google Calendar in one click. Papyrus reads your events and learns your existing commitments and patterns.",
  },
  {
    icon: MessageSquare,
    title: "Chat to plan",
    body: "Each morning, describe your day in plain language — energy, context, constraints. Papyrus schedules around what matters.",
  },
  {
    icon: CalendarCheck,
    title: "Confirm, done",
    body: "Review the proposed schedule and confirm. Events are written directly to your calendar. No syncing, no guessing.",
  },
];

function HowItWorks() {
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
          How it works
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
          Three steps to a calmer day
        </motion.h2>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 24,
          }}
        >
          {STEPS.map((step, i) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.title}
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
                  {step.title}
                </h3>
                <p
                  style={{
                    fontSize: 14,
                    lineHeight: 1.65,
                    color: "var(--text-muted)",
                    maxWidth: "48ch",
                  }}
                >
                  {step.body}
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
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ── CTA strip ─────────────────────────────────────────────────────────────────

function CTAStrip() {
  return (
    <section
      style={{
        padding: "96px 48px",
        textAlign: "center",
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
            marginBottom: 28,
          }}
        >
          Ready to take back your time?
        </h2>
        <a
          href="https://forms.gle/sSpeWWJFEp48qANE6"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "12px 36px",
            borderRadius: 8,
            background: "var(--accent)",
            color: "var(--bg)",
            fontSize: 14,
            textDecoration: "none",
            fontFamily: "var(--font-literata)",
            transition: "background 0.15s",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLElement).style.background =
              "var(--accent-hover)")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLElement).style.background = "var(--accent)")
          }
        >
          Join the waitlist
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
      <HowItWorks />
      <CTAStrip />
    </main>
  );
}
