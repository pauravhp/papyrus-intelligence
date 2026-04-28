// frontend/components/HowToGuide.tsx
"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { HOWTO_PROMPT } from "@/lib/howtoPrompt";

interface HowToGuideProps {
  open: boolean;
  onClose: () => void;
}

const TOTAL_STEPS = 8;

// ── shared style constants ─────────────────────────────────────────────────

const EYEBROW: React.CSSProperties = {
  fontSize: 10,
  textTransform: "uppercase" as const,
  letterSpacing: "0.1em",
  color: "var(--text-faint)",
  marginBottom: 12,
  fontFamily: "var(--font-literata)",
};

const HEADING: React.CSSProperties = {
  fontFamily: "var(--font-gilda)",
  fontSize: "1.4rem",
  fontWeight: 400,
  color: "var(--text)",
  lineHeight: 1.25,
  marginBottom: 12,
  letterSpacing: "-0.01em",
};

const BODY: React.CSSProperties = {
  fontSize: 13,
  color: "var(--text-secondary)",
  lineHeight: 1.65,
  marginBottom: 18,
  fontFamily: "var(--font-literata)",
};

const CARD: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  padding: "14px 16px",
};

const LABEL_CHIP_BASE: React.CSSProperties = {
  borderRadius: 20,
  padding: "2px 10px",
  fontSize: 11,
  fontFamily: "var(--font-literata)",
  whiteSpace: "nowrap" as const,
  flexShrink: 0,
  minWidth: 110,
  textAlign: "center" as const,
  marginTop: 1,
};

const ACTIVE_CHIP: React.CSSProperties = {
  ...LABEL_CHIP_BASE,
  background: "var(--accent-tint)",
  color: "var(--accent)",
  border: "1px solid var(--accent-soft)",
};

const MUTED_CHIP: React.CSSProperties = {
  ...LABEL_CHIP_BASE,
  background: "var(--surface-raised)",
  color: "var(--text-muted)",
  border: "1px solid var(--border)",
};

const TIME_CHIP: React.CSSProperties = {
  background: "var(--accent-tint)",
  color: "var(--accent)",
  border: "1px solid var(--accent-soft)",
  borderRadius: 20,
  padding: "4px 12px",
  fontSize: 12,
  fontFamily: "var(--font-literata)",
};

// ── per-step content ───────────────────────────────────────────────────────

function renderStepContent(stepIndex: number, copied: boolean, onCopy: () => void) {
  switch (stepIndex) {
    // ── Step 0: Welcome ──
    case 0:
      return (
        <div>
          <div style={EYEBROW}>Step 1 of {TOTAL_STEPS}</div>
          <div style={HEADING}>You're set up.<br />Here's how Papyrus thinks.</div>
          <div style={BODY}>
            Papyrus connects your Todoist tasks and Google Calendar. Each morning, tell it how
            you're feeling — it proposes a time-blocked day. You review, confirm, and it writes
            the plan to your calendar.
            <br /><br />
            And when things slip mid-day — because Tuesdays happen — you can <em>replan</em>
            the afternoon in one calm gesture. Not a restart. An update.
            <br /><br />
            For it to plan (and replan) well, your tasks need to speak its language. This guide
            covers exactly that.
            <p style={{ marginTop: 12 }}>
              On the{" "}
              <strong style={{ fontWeight: 600 }}>Rhythms</strong>{" "}
              page you can set recurring commitments — exercise, reading, deep work — with
              a <em>Scheduling hint</em> that tells Papyrus when they fit best (e.g.{" "}
              <em>"mornings only"</em> or <em>"before deep work"</em>).
            </p>
            <p style={{ marginTop: 12, fontSize: 12, color: "var(--text-faint)", fontStyle: "italic" as const }}>
              One quick check before you start planning: in Todoist, go to{" "}
              <strong style={{ fontWeight: 600 }}>Settings → Integrations → Calendar</strong>{" "}
              and turn off the Google Calendar sync if it's on. Papyrus writes events to your
              calendar directly, so leaving Todoist's sync on would show every scheduled task
              twice. Papyrus tries to spot this during setup and will warn you — but you'll
              need to flip the toggle yourself.
            </p>
          </div>
        </div>
      );

    // ── Step 1: Copy Prompt (moved from Step 6 — quick-start shortcut) ──
    case 1:
      return (
        <div>
          <div style={EYEBROW}>Step 2 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Bring a Papyrus coach with you</div>
          <div style={BODY}>
            Paste this into Claude, ChatGPT, or Gemini and it becomes a Papyrus
            coach you can ask anything: how to set up your Todoist labels, why a
            task didn't get scheduled, how to phrase a context note when your
            afternoon slips, what to type for a replan. It explains the reasoning
            behind Papyrus's choices — not just the mechanics.
            <br /><br />
            It won't try to <em>be</em> Papyrus or design a UI for you — it's
            there to answer questions, like a patient friend who already knows
            the app.
            <br /><br />
            <em style={{ color: "var(--text-faint)" }}>
              Optional. The next five slides walk through everything in detail —
              skip this if you'd rather just learn by clicking.
            </em>
          </div>
          <div>
            <button
              onClick={onCopy}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                background: "var(--surface-raised)", border: "1px solid var(--border)",
                borderRadius: 10, padding: "11px 14px", cursor: "pointer",
                fontFamily: "var(--font-literata)", fontSize: 13, color: "var(--text-secondary)",
                width: "100%", marginBottom: 10, textAlign: "left" as const,
                transition: "background 0.15s",
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
                <rect x="5" y="1" width="10" height="12" rx="2" stroke="var(--border-strong)" strokeWidth="1.5" />
                <rect x="1" y="4" width="10" height="12" rx="2" fill="var(--surface-raised)" stroke="var(--border-strong)" strokeWidth="1.5" />
              </svg>
              {copied ? "Copied ✓" : "Copy setup prompt"}
            </button>
            <div style={{
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, padding: "10px 12px",
              fontSize: 10, color: "var(--text-muted)", lineHeight: 1.6,
              maxHeight: 100, overflow: "hidden", position: "relative" as const,
              fontFamily: "var(--font-literata)",
            }}>
              {HOWTO_PROMPT.slice(0, 220)}…
              <div style={{
                position: "absolute", bottom: 0, left: 0, right: 0, height: 32,
                background: "linear-gradient(transparent, var(--surface))",
              }} />
            </div>
          </div>
        </div>
      );

    // ── Step 2: Scheduling Labels ──
    case 2:
      return (
        <div>
          <div style={EYEBROW}>Step 3 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Label tasks so Papyrus knows how to place them</div>
          <div style={BODY}>
            These labels tell Papyrus the cognitive weight and placement rules for each task —
            not just when, but <em>how</em> to schedule it.
          </div>
          <div style={CARD}>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[
                { chip: ACTIVE_CHIP, label: "@deep-work", desc: "Focused, uninterrupted. Morning or peak windows only. Never back-to-back." },
                { chip: ACTIVE_CHIP, label: "@admin", desc: "Low-cognitive — emails, coordination. Flexible; good for afternoon." },
                { chip: ACTIVE_CHIP, label: "@quick", desc: "Under 15 min. Batched into transition gaps between larger blocks." },
                { chip: MUTED_CHIP, label: "@waiting", desc: "Blocked on someone. Never auto-scheduled — surfaces in weekly review." },
                { chip: MUTED_CHIP, label: "@in-progress", desc: "Partially done. Treated as higher urgency than unstarted tasks." },
                { chip: MUTED_CHIP, label: "@recurring-review", desc: "For tasks like “review goals weekly” — surfaces in your weekly review only, never in daily plans." },
              ].map(({ chip, label, desc }) => (
                <div key={label} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                  <span style={chip}>{label}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45, paddingTop: 3 }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      );

    // ── Step 3: Priorities ──
    case 3:
      return (
        <div>
          <div style={EYEBROW}>Step 4 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Priority tells Papyrus when to schedule it</div>
          <div style={BODY}>
            Set priority in Todoist to control urgency. Papyrus uses this to decide what makes
            today's plan and what waits.
          </div>
          <div style={CARD}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {[
                { flag: "var(--accent)", label: "P1", meaning: "Schedule today — no exceptions" },
                { flag: "#d4a55a",       label: "P2", meaning: "This week — fit where possible" },
                { flag: "var(--border-strong)", label: "P3", meaning: "Someday — only if time allows" },
                { flag: "var(--border)", label: "P4", meaning: "Reference only — never scheduled" },
              ].map(({ flag, label, meaning }) => (
                <div key={label} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "7px 10px", borderRadius: 8,
                  background: "var(--surface-raised)", border: "1px solid var(--border)",
                }}>
                  <div style={{ width: 3, height: 26, borderRadius: 2, background: flag, flexShrink: 0 }} />
                  <span style={{ fontSize: 10, fontWeight: 500, color: "var(--text-muted)", textTransform: "uppercase" as const, letterSpacing: "0.06em", minWidth: 18 }}>{label}</span>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{meaning}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      );

    // ── Step 4: Time Estimate Labels ──
    case 4:
      return (
        <div>
          <div style={EYEBROW}>Step 5 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Add a time label — or your task won't be scheduled</div>
          <div style={BODY}>
            Time estimates are Todoist labels, not text in the task name. If a task has no time
            label, Papyrus skips it silently. Pick the closest estimate — it doesn't need to be exact.
          </div>
          <div style={CARD}>
            <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6, marginBottom: 14 }}>
              {["@10min", "@15min", "@30min", "@45min", "@60min", "@75min", "@90min", "@2h", "@3h"].map(t => (
                <span key={t} style={TIME_CHIP}>{t}</span>
              ))}
            </div>
            <div style={{ height: 1, background: "var(--border)", marginBottom: 12 }} />
            <div style={{ fontSize: 10, textTransform: "uppercase" as const, letterSpacing: "0.08em", color: "var(--text-faint)", marginBottom: 8, fontFamily: "var(--font-literata)" }}>
              Why 3h is the maximum
            </div>
            <div style={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 8 }}>
                <div style={{ flex: 1, height: 20, borderRadius: 4, background: "var(--accent-tint)", border: "1px solid var(--accent-soft)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--accent)", fontFamily: "var(--font-literata)" }}>
                  @90min
                </div>
                <div style={{ width: 32, height: 20, borderRadius: 4, background: "var(--surface)", border: "1px dashed var(--border)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, color: "var(--text-faint)", flexShrink: 0 }}>
                  break
                </div>
                <div style={{ flex: 1, height: 20, borderRadius: 4, background: "var(--accent-tint)", border: "1px solid var(--accent-soft)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "var(--accent)", fontFamily: "var(--font-literata)" }}>
                  @90min
                </div>
                <span style={{ fontSize: 10, color: "var(--text-faint)", marginLeft: 4, flexShrink: 0 }}>= 3h</span>
              </div>
              <div style={{ fontSize: 10, color: "var(--text-faint)", fontStyle: "italic" as const, lineHeight: 1.5, fontFamily: "var(--font-literata)" }}>
                Your brain cycles through ~90-min focus windows (ultradian rhythms). Beyond two cycles, cognitive output drops regardless of motivation.
              </div>
            </div>
          </div>
        </div>
      );

    // ── Step 5: Context Notes ──
    case 5:
      return (
        <div>
          <div style={EYEBROW}>Step 6 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Tell Papyrus how you're feeling before you plan</div>
          <div style={BODY}>
            Say anything in chat before asking to plan. Papyrus uses this to adjust which tasks
            get selected, how tightly they're packed, and which get pushed to tomorrow.
            <br /><br />
            The same kind of note works during a <em>replan</em> — "running behind, skip the gym",
            "roommate's sick, light afternoon" — so the recovery still feels like yours.
          </div>
          <div style={CARD}>
            <div style={{
              alignSelf: "flex-end", marginLeft: "auto",
              background: "var(--accent-hover)", color: "#fff9f0",
              borderRadius: "16px 16px 4px 16px",
              padding: "8px 13px", fontSize: 12, lineHeight: 1.4,
              maxWidth: "80%", marginBottom: 10, fontStyle: "italic" as const,
              display: "inline-block",
              boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
            }}>
              "plan light today, low energy — skip anything physical"
            </div>
            <div style={{ textAlign: "center" as const, fontSize: 10, color: "var(--text-faint)", marginBottom: 8 }}>↓ Papyrus adjusts the plan</div>
            <div style={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", display: "flex", flexDirection: "column" as const, gap: 5 }}>
              {[
                { time: "9:00", width: 55, task: "Reply to emails" },
                { time: "9:30", width: 38, task: "Review PR" },
                { time: "10:15", width: 70, task: "Write update doc" },
              ].map(({ time, width, task }) => (
                <div key={time} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 10, color: "var(--text-faint)", minWidth: 36, fontFamily: "var(--font-literata)" }}>{time}</span>
                  <div style={{ width, height: 5, borderRadius: 3, background: "var(--accent-soft)", flexShrink: 0 }} />
                  <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{task}</span>
                </div>
              ))}
              <div style={{ fontSize: 10, color: "var(--text-faint)", fontStyle: "italic" as const, marginTop: 2 }}>Deep work moved to tomorrow · Gym skipped</div>
            </div>
          </div>
        </div>
      );

    // ── Step 6: Two Moments ──
    case 6:
      return (
        <div>
          <div style={EYEBROW}>Step 7 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Two moments, one coach</div>
          <div style={BODY}>
            Things going off-plan isn't failure — it's just Tuesday. Papyrus is designed for both
            moments: building the day in the morning, and <em>replanning</em> calmly in the
            afternoon. Not a restart. An update to the rest of your day, grounded in what actually
            happened.
          </div>
          <div style={CARD}>
            <div style={{ display: "flex", gap: 10 }}>
              {/* Morning */}
              <div style={{ flex: 1, background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
                <div style={{ fontSize: 10, textTransform: "uppercase" as const, letterSpacing: "0.1em", color: "var(--text-faint)", marginBottom: 10 }}>Morning · Plan</div>
                <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 18, padding: "6px 10px", fontSize: 11, color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                  <span style={{ flex: 1 }}>plan my day</span>
                  <div style={{ width: 16, height: 16, borderRadius: "50%", background: "var(--accent)", flexShrink: 0 }} />
                </div>
                <div style={{ fontSize: 10, color: "var(--text-faint)", lineHeight: 1.45 }}>Type anything in chat to get a time-blocked schedule. Papyrus waits for your confirmation before touching your calendar.</div>
              </div>
              {/* Afternoon */}
              <div style={{ flex: 1, background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
                <div style={{ fontSize: 10, textTransform: "uppercase" as const, letterSpacing: "0.1em", color: "var(--text-faint)", marginBottom: 10 }}>Afternoon · Replan</div>
                <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "7px 0", fontSize: 12, color: "var(--text-secondary)", textAlign: "center" as const, marginBottom: 6 }}>↺ Replan</div>
                <div style={{ display: "flex", gap: 3, marginBottom: 8 }}>
                  {[
                    { label: "✓ done", active: true },
                    { label: "→ tmrw", active: false },
                    { label: "keep", active: false },
                  ].map(({ label, active }) => (
                    <div key={label} style={{ flex: 1, textAlign: "center" as const, padding: "3px 0", borderRadius: 5, fontSize: 10, border: "1px solid var(--border)", color: active ? "var(--accent)" : "var(--text-muted)", background: active ? "var(--accent-tint)" : "var(--surface)" }}>{label}</div>
                  ))}
                </div>
                <div style={{ fontSize: 10, color: "var(--text-faint)", lineHeight: 1.45 }}>Triage what happened, tell Papyrus how you feel, get a calmer afternoon. The morning's plan doesn't fail — it gets updated.</div>
              </div>
            </div>
          </div>
        </div>
      );

    // ── Step 7: Closing the day ──
    case 7:
      return (
        <div>
          <div style={EYEBROW}>Step 8 of {TOTAL_STEPS}</div>
          <div style={HEADING}>Closing the day</div>
          <div style={BODY}>
            When the day winds down, a small <strong>Review →</strong> pill appears in the
            today header. It opens a stepper covering every day from the last week that
            never got reviewed — usually just today, but if you skipped yesterday it&rsquo;ll
            be there too. Mark each task done or incomplete (with a reason if you want),
            and Papyrus closes the loop with one warm summary line at the end.
          </div>
          <div style={CARD}>
            <div style={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 10, textTransform: "uppercase" as const, letterSpacing: "0.1em", color: "var(--text-faint)", marginBottom: 10 }}>End of day</div>
              <div style={{ display: "inline-flex", alignItems: "center", padding: "6px 12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12, color: "var(--text)", marginBottom: 10 }}>
                Review →
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--text-secondary)" }}>
                <span>Mon · Apr 27</span>
                <span>4/5 tasks · 1/2 rhythms</span>
              </div>
              <div style={{ fontSize: 10, color: "var(--text-faint)", lineHeight: 1.45, marginTop: 8 }}>
                Whole-day-or-nothing. Save &amp; exit any time; the queue picks up where you left off.
              </div>
            </div>
          </div>
        </div>
      );

    default:
      return null;
  }
}

// ── main component ─────────────────────────────────────────────────────────

export default function HowToGuide({ open, onClose }: HowToGuideProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const [direction, setDirection] = useState(1);
  const [copied, setCopied] = useState(false);

  const goTo = (next: number) => {
    setDirection(next > stepIndex ? 1 : -1);
    setStepIndex(next);
  };

  const handleClose = () => {
    localStorage.setItem("howto_seen", "true");
    setStepIndex(0);
    setDirection(1);
    setCopied(false);
    onClose();
  };

  const handleFinish = () => {
    localStorage.setItem("howto_seen", "true");
    setStepIndex(0);
    setDirection(1);
    setCopied(false);
    onClose();
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(HOWTO_PROMPT);
    } catch {
      // fallback for older browsers
      const ta = document.createElement("textarea");
      ta.value = HOWTO_PROMPT;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isLast = stepIndex === TOTAL_STEPS - 1;

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            key="howto-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(245,239,224,0.55)",
              zIndex: 55,
            }}
          />

          {/* Drawer */}
          <motion.div
            key="howto-drawer"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 280, damping: 26 }}
            style={{
              position: "fixed",
              right: 0,
              top: 0,
              bottom: 0,
              width: "min(420px, 100vw)",
              maxWidth: "100vw",
              background: "var(--bg)",
              borderLeft: "1px solid var(--border)",
              zIndex: 60,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Close button */}
            <button
              onClick={handleClose}
              aria-label="Close guide"
              style={{
                position: "absolute", top: 14, right: 16,
                width: 28, height: 28, borderRadius: "50%",
                background: "var(--surface)", border: "1px solid var(--border)",
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer", color: "var(--text-muted)", zIndex: 1,
              }}
            >
              <X size={13} />
            </button>

            {/* Step content (animated) — overflowX hidden to clip the slide
                animation; overflowY auto so step 0's longer copy can scroll on
                short / mobile viewports instead of getting visually cut off. */}
            <div style={{
              flex: 1,
              padding: "28px 26px 16px",
              overflowX: "hidden",
              overflowY: "auto",
              WebkitOverflowScrolling: "touch",
            }}>
              <AnimatePresence mode="wait" custom={direction}>
                <motion.div
                  key={stepIndex}
                  custom={direction}
                  initial={{ opacity: 0, x: direction * 40 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: direction * -40 }}
                  transition={{ duration: 0.18, ease: "easeOut" }}
                >
                  {renderStepContent(stepIndex, copied, handleCopy)}
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Bottom nav */}
            <div style={{
              padding: "14px 26px 22px",
              borderTop: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
            }}>
              {/* Back — 44×44 tap target on mobile, visually unchanged */}
              <button
                onClick={() => goTo(stepIndex - 1)}
                aria-label="Previous step"
                style={{
                  width: 44, height: 44,
                  minWidth: 44, minHeight: 44,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: "var(--text-muted)", fontSize: 22, background: "none", border: "none",
                  cursor: "pointer", flexShrink: 0,
                  opacity: stepIndex === 0 ? 0 : 1,
                  pointerEvents: stepIndex === 0 ? "none" : "auto",
                  marginLeft: -10,
                }}
              >
                ‹
              </button>

              {/* Dots */}
              <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
                {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
                  <button
                    key={i}
                    onClick={() => goTo(i)}
                    aria-label={`Go to step ${i + 1}`}
                    style={{
                      width: i === stepIndex ? 18 : 6,
                      height: 6,
                      borderRadius: i === stepIndex ? 3 : "50%",
                      background: i === stepIndex ? "var(--accent)" : "var(--border-strong)",
                      border: "none",
                      cursor: "pointer",
                      padding: 0,
                      transition: "all 0.2s",
                      flexShrink: 0,
                    }}
                  />
                ))}
              </div>

              {/* Next / Finish */}
              <motion.button
                onClick={isLast ? handleFinish : () => goTo(stepIndex + 1)}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                style={{
                  background: "var(--accent)",
                  color: "var(--surface-raised)",
                  border: "none",
                  borderRadius: 22,
                  padding: isLast ? "8px 12px" : "8px 16px",
                  fontFamily: "var(--font-literata)",
                  fontSize: isLast ? 12 : 13,
                  cursor: "pointer",
                  flexShrink: 0,
                  whiteSpace: "nowrap" as const,
                }}
              >
                {isLast ? "Start planning →" : "Next →"}
              </motion.button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
