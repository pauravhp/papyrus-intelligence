"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { motion } from "framer-motion";
import { ScanLine, Sparkles, CalendarCheck } from "lucide-react";

// Load OrbField only on the client (no SSR — needs WebGL)
const OrbField = dynamic(() => import("./OrbField"), {
  ssr: false,
  loading: () => <div className="w-full h-full" style={{ background: "#080810" }} />,
});

// ── Navigation ─────────────────────────────────────────────────────────────

function Nav() {
  return (
    <nav
      className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 py-4"
      style={{
        background:
          "linear-gradient(to bottom, rgba(8,8,16,0.8) 0%, transparent 100%)",
      }}
    >
      <span
        className="font-display text-white text-xl tracking-tight"
        style={{ letterSpacing: "-0.02em" }}
      >
        schedule for me
      </span>
      <Link
        href="/login"
        className="text-sm text-white/70 hover:text-white border border-white/20 hover:border-white/40 rounded-lg px-4 py-1.5 transition-colors"
      >
        Sign in
      </Link>
    </nav>
  );
}

// ── Hero section ───────────────────────────────────────────────────────────

function Hero() {
  const scrollToHowItWorks = () => {
    document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <section
      className="relative h-screen overflow-hidden"
      style={{ background: "#080810" }}
    >
      {/* 3D canvas fills the entire hero */}
      <div className="absolute inset-0">
        <OrbField />
      </div>

      {/* Radial gradient overlay for text legibility */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(8,8,16,0.45) 0%, transparent 100%)",
        }}
      />

      {/* Hero text */}
      <div className="relative z-10 flex flex-col items-center justify-center h-full text-center px-4">
        <motion.h1
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          className="font-display text-white leading-tight"
          style={{
            fontSize: "clamp(2.5rem, 6vw, 4.5rem)",
            letterSpacing: "-0.03em",
            textShadow: "0 0 60px rgba(99,102,241,0.3)",
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
          className="mt-6 max-w-md text-white/60"
          style={{ fontSize: "clamp(1rem, 2vw, 1.125rem)", lineHeight: 1.65 }}
        >
          AI-powered scheduling that learns your patterns, respects your energy,
          and plans your day — automatically.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="mt-10 flex items-center gap-3 flex-wrap justify-center"
        >
          <Link
            href="/login"
            className="inline-flex items-center justify-center px-6 py-3 rounded-xl text-sm font-medium text-white transition-all"
            style={{
              background: "#6366f1",
              boxShadow: "0 0 24px rgba(99,102,241,0.45)",
            }}
            onMouseEnter={(e) =>
              ((e.currentTarget as HTMLElement).style.boxShadow =
                "0 0 36px rgba(99,102,241,0.65)")
            }
            onMouseLeave={(e) =>
              ((e.currentTarget as HTMLElement).style.boxShadow =
                "0 0 24px rgba(99,102,241,0.45)")
            }
          >
            Get started
          </Link>
          <button
            onClick={scrollToHowItWorks}
            className="inline-flex items-center justify-center px-6 py-3 rounded-xl text-sm font-medium text-white/70 hover:text-white border border-white/20 hover:border-white/40 transition-colors"
          >
            See how it works
          </button>
        </motion.div>
      </div>

      {/* Scroll indicator */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.4 }}
        transition={{ delay: 1.2, duration: 0.6 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1"
      >
        <div className="w-px h-8 bg-white/30 animate-pulse" />
      </motion.div>
    </section>
  );
}

// ── How it works ──────────────────────────────────────────────────────────

const STEPS = [
  {
    icon: ScanLine,
    title: "Connect your calendar",
    body: "Link Google Calendar in one click. We read your events and learn your existing commitments and patterns.",
  },
  {
    icon: Sparkles,
    title: "AI learns your patterns",
    body: "Our LLM pipeline studies your energy, deep-work windows, and scheduling habits to understand how you actually work.",
  },
  {
    icon: CalendarCheck,
    title: "Your day, planned",
    body: "Every morning, get a daily plan that slots your tasks into the right windows — automatically written back to Todoist.",
  },
];

function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="py-24 px-6"
      style={{ background: "#080810" }}
    >
      <div className="max-w-5xl mx-auto">
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          viewport={{ once: true }}
          className="text-center text-xs font-medium tracking-widest uppercase mb-4"
          style={{ color: "#6366f1" }}
        >
          How it works
        </motion.p>

        <motion.h2
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.05 }}
          viewport={{ once: true }}
          className="font-display text-white text-center mb-16"
          style={{
            fontSize: "clamp(1.75rem, 4vw, 2.5rem)",
            letterSpacing: "-0.025em",
          }}
        >
          Three steps to a smarter day
        </motion.h2>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {STEPS.map((step, i) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.title}
                initial={{ opacity: 0, y: 24 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: i * 0.12 }}
                viewport={{ once: true }}
                className="relative rounded-2xl p-6 flex flex-col gap-4"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{ background: "rgba(99,102,241,0.15)" }}
                >
                  <Icon size={20} color="#6366f1" strokeWidth={1.5} />
                </div>
                <div>
                  <h3
                    className="font-display text-white text-lg mb-2"
                    style={{ letterSpacing: "-0.015em" }}
                  >
                    {step.title}
                  </h3>
                  <p
                    className="text-sm leading-relaxed"
                    style={{ color: "#64748b" }}
                  >
                    {step.body}
                  </p>
                </div>
                <span
                  className="absolute top-5 right-5 font-display text-5xl font-bold select-none"
                  style={{ color: "rgba(255,255,255,0.04)" }}
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

// ── CTA strip ─────────────────────────────────────────────────────────────

function CTAStrip() {
  return (
    <section
      className="py-24 px-6 text-center"
      style={{ background: "#080810" }}
    >
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7 }}
        viewport={{ once: true }}
        className="max-w-xl mx-auto"
      >
        <h2
          className="font-display text-white mb-6"
          style={{
            fontSize: "clamp(1.75rem, 4vw, 2.25rem)",
            letterSpacing: "-0.025em",
          }}
        >
          Ready to take back your time?
        </h2>
        <Link
          href="/login"
          className="inline-flex items-center justify-center px-8 py-3.5 rounded-xl text-sm font-medium text-white transition-all"
          style={{
            background: "#6366f1",
            boxShadow: "0 0 24px rgba(99,102,241,0.4)",
          }}
          onMouseEnter={(e) =>
            ((e.currentTarget as HTMLElement).style.boxShadow =
              "0 0 40px rgba(99,102,241,0.6)")
          }
          onMouseLeave={(e) =>
            ((e.currentTarget as HTMLElement).style.boxShadow =
              "0 0 24px rgba(99,102,241,0.4)")
          }
        >
          Start for free
        </Link>
      </motion.div>
    </section>
  );
}

// ── Root export ────────────────────────────────────────────────────────────

export default function LandingClient() {
  return (
    <main className="flex flex-col">
      <Nav />
      <Hero />
      <HowItWorks />
      <CTAStrip />
    </main>
  );
}
