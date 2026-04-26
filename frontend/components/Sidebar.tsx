// frontend/components/Sidebar.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CalendarDays, Activity, Settings2, X, Sun, Moon, LogOut, HelpCircle, MessageCircle } from "lucide-react";
import { usePostHog } from "posthog-js/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/utils/supabase/client";
import HowToGuide from "@/components/HowToGuide";
import { useTheme } from "@/components/ThemeProvider";

const NAV_ITEMS = [
  { icon: CalendarDays,  label: "Today",    href: "/today"              },
  { icon: Activity,      label: "Rhythms",  href: "/rhythms"            },
  { icon: Settings2,     label: "Settings", href: "/dashboard/settings" },
] as const;

const ICON_BTN: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: 40,
  height: 40,
  borderRadius: 10,
  border: "none",
  background: "transparent",
  cursor: "pointer",
  transition: "background 0.15s",
};

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggle } = useTheme();
  const [guideOpen, setGuideOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackNps, setFeedbackNps] = useState<number | null>(null);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const posthog = usePostHog();

  useEffect(() => {
    const seen = localStorage.getItem("howto_seen");
    if (!seen) {
      const t = setTimeout(() => setGuideOpen(true), 800);
      return () => clearTimeout(t);
    }
  }, []);
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.push("/login");
  };

  const handleFeedbackSubmit = () => {
    if (!feedbackText.trim() && feedbackNps === null) return;
    posthog?.capture("feedback_submitted", {
      message: feedbackText.trim() || null,
      nps_score: feedbackNps,
    });
    setFeedbackSent(true);
    setTimeout(() => {
      setFeedbackOpen(false);
      setFeedbackSent(false);
      setFeedbackText("");
      setFeedbackNps(null);
    }, 1800);
  };


  return (
    <>
      {/* Sidebar strip */}
      <nav
        style={{
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          width: 56,
          background: "var(--surface)",
          backdropFilter: "blur(8px)",
          borderRight: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          paddingTop: 20,
          paddingBottom: 20,
          gap: 4,
          zIndex: 40,
        }}
      >
        {NAV_ITEMS.map(({ icon: Icon, label, href }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href} title={label} style={{ textDecoration: "none" }}>
              <motion.div
                whileHover={{ scale: 1.1, background: "var(--accent-tint)" }}
                whileTap={{ scale: 0.92 }}
                style={{
                  ...ICON_BTN,
                  background: active ? "var(--accent-tint)" : "transparent",
                  color: active ? "var(--accent)" : "var(--text-muted)",
                }}
              >
                <Icon size={18} />
              </motion.div>
            </Link>
          );
        })}

        <div style={{ flex: 1 }} />

        {/* Sign out */}
        <motion.button
          onClick={handleSignOut}
          title="Sign out"
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.92 }}
          style={{ ...ICON_BTN, color: "var(--text-muted)" }}
        >
          <LogOut size={18} />
        </motion.button>

        {/* Theme toggle */}
        <motion.button
          onClick={toggle}
          title={theme === "light" ? "Switch to dark" : "Switch to light"}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.92 }}
          style={{ ...ICON_BTN, color: "var(--text-muted)" }}
        >
          {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
        </motion.button>

        {/* How-to guide */}
        <motion.button
          onClick={() => setGuideOpen(true)}
          title="How-to guide"
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.92 }}
          style={{
            ...ICON_BTN,
            color: guideOpen ? "var(--accent)" : "var(--text-muted)",
            background: guideOpen ? "var(--accent-tint)" : "transparent",
          }}
        >
          <HelpCircle size={18} />
        </motion.button>

        {/* Feedback button */}
        <motion.button
          onClick={() => setFeedbackOpen(true)}
          title="Share feedback"
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.92 }}
          style={{
            ...ICON_BTN,
            color: feedbackOpen ? "var(--accent)" : "var(--text-muted)",
            background: feedbackOpen ? "var(--accent-tint)" : "transparent",
          }}
        >
          <MessageCircle size={18} />
        </motion.button>
      </nav>

      <AnimatePresence>
        {feedbackOpen && (
          <>
            <motion.div
              key="feedback-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              onClick={() => setFeedbackOpen(false)}
              style={{
                position: "fixed",
                inset: 0,
                background: "rgba(44,26,14,0.3)",
                zIndex: 45,
              }}
            />
            <motion.div
              key="feedback-panel"
              initial={{ x: -340, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: -340, opacity: 0 }}
              transition={{ type: "spring", stiffness: 280, damping: 28 }}
              style={{
                position: "fixed",
                left: 56,
                top: 0,
                bottom: 0,
                width: 340,
                background: "var(--bg)",
                borderRight: "1px solid var(--border)",
                zIndex: 50,
                padding: "24px 20px",
                display: "flex",
                flexDirection: "column",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <h2
                  className="font-display"
                  style={{ color: "var(--text)", fontSize: 18, fontWeight: 400, margin: 0 }}
                >
                  Share feedback
                </h2>
                <button
                  onClick={() => setFeedbackOpen(false)}
                  style={{ ...ICON_BTN, color: "var(--text-muted)" }}
                >
                  <X size={16} />
                </button>
              </div>

              {feedbackSent ? (
                <p style={{ color: "var(--text-muted)", fontSize: 14, fontStyle: "italic" }}>
                  Thank you — it means a lot.
                </p>
              ) : (
                <>
                  <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20, fontStyle: "italic", lineHeight: 1.6 }}>
                    No pressure. Anything is helpful — or nothing at all is fine too.
                  </p>

                  {/* NPS */}
                  <p style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-faint)", marginBottom: 10 }}>
                    How likely are you to recommend Papyrus?
                  </p>
                  <div style={{ display: "flex", gap: 6, marginBottom: 20, flexWrap: "wrap" }}>
                    {[0,1,2,3,4,5,6,7,8,9,10].map((n) => (
                      <button
                        key={n}
                        onClick={() => setFeedbackNps(feedbackNps === n ? null : n)}
                        style={{
                          width: 34,
                          height: 34,
                          borderRadius: 8,
                          border: "1px solid var(--border-strong)",
                          background: feedbackNps === n ? "var(--accent)" : "var(--surface)",
                          color: feedbackNps === n ? "#fff" : "var(--text-muted)",
                          fontSize: 13,
                          cursor: "pointer",
                          fontFamily: "var(--font-literata)",
                          transition: "background 0.12s, color 0.12s",
                        }}
                      >
                        {n}
                      </button>
                    ))}
                  </div>

                  {/* Message */}
                  <p style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-faint)", marginBottom: 8 }}>
                    Anything else? (optional)
                  </p>
                  <textarea
                    value={feedbackText}
                    onChange={(e) => setFeedbackText(e.target.value)}
                    placeholder="What would make Papyrus more useful for you?"
                    rows={4}
                    style={{
                      width: "100%",
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      padding: "10px 12px",
                      fontSize: 13,
                      fontFamily: "var(--font-literata)",
                      color: "var(--text)",
                      resize: "none",
                      outline: "none",
                      lineHeight: 1.6,
                      marginBottom: 16,
                    }}
                  />

                  <button
                    onClick={handleFeedbackSubmit}
                    disabled={!feedbackText.trim() && feedbackNps === null}
                    style={{
                      padding: "10px 0",
                      background: (!feedbackText.trim() && feedbackNps === null) ? "var(--surface)" : "var(--accent)",
                      color: (!feedbackText.trim() && feedbackNps === null) ? "var(--text-faint)" : "#fff",
                      border: "none",
                      borderRadius: 9,
                      fontSize: 13,
                      fontFamily: "var(--font-literata)",
                      cursor: (!feedbackText.trim() && feedbackNps === null) ? "not-allowed" : "pointer",
                      transition: "background 0.15s",
                    }}
                  >
                    Send feedback
                  </button>
                </>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>

      <HowToGuide
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
      />
    </>
  );
}
