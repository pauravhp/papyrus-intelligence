import type { Metadata } from "next";
import { Gilda_Display, Literata } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/ThemeProvider";

const gildaDisplay = Gilda_Display({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-gilda",
  display: "swap",
});

const literata = Literata({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-literata",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Papyrus — AI-powered scheduling",
  description:
    "A calm scheduling coach that plans your day, respects your energy, and adapts when things slip.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${gildaDisplay.variable} ${literata.variable} h-full`}
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
