// frontend/app/dashboard/today/ResearchSnippet.tsx
"use client";

import { useMemo } from "react";

const SNIPPETS = [
  {
    quote: "When people form specific 'when-then' plans, follow-through increases by up to 300%.",
    attribution: "Gollwitzer, 1999",
  },
  {
    quote: "Seeing what you planned — not just what you did — is how you calibrate future estimates.",
    attribution: "Kahneman",
  },
  {
    quote: "The best planners don't plan less. They build in recovery time.",
    attribution: "Hofstadter's Law",
  },
  {
    quote: "Reviewing the day ahead each morning measurably reduces decision fatigue by noon.",
    attribution: "Baumeister et al.",
  },
];

export default function ResearchSnippet() {
  // Pick a random snippet once per mount — stable across re-renders
  const snippet = useMemo(
    () => SNIPPETS[Math.floor(Math.random() * SNIPPETS.length)],
    []
  );

  return (
    <div style={{ marginTop: 56, paddingTop: 24, borderTop: "1px solid var(--border)" }}>
      <p style={{
        fontSize: 10,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--accent)",
        fontFamily: "var(--font-literata)",
        marginBottom: 8,
      }}>
        From the research
      </p>
      <p style={{
        fontSize: 13,
        fontStyle: "italic",
        color: "var(--text-muted)",
        fontFamily: "var(--font-literata)",
        lineHeight: 1.6,
        maxWidth: "60ch",
      }}>
        &ldquo;{snippet.quote}&rdquo;
      </p>
      <p style={{
        fontSize: 11,
        color: "var(--text-faint)",
        fontFamily: "var(--font-literata)",
        marginTop: 6,
      }}>
        — {snippet.attribution}
      </p>
    </div>
  );
}
