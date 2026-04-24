// frontend/components/Sidebar.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { CalendarDays, Activity, Settings2, Sun, Moon, LogOut, HelpCircle } from "lucide-react";
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
      </nav>

      <HowToGuide
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
      />
    </>
  );
}
