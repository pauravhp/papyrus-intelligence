// frontend/app/onboard/page.tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import SetupStage from "./SetupStage";
import DiscoverStage from "./DiscoverStage";

type Step = "setup" | "discover";

export default function OnboardPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("setup");
  const [timezone, setTimezone] = useState("UTC");
  const [calendarIds, setCalendarIds] = useState<string[]>([]);

  const handleSetupComplete = (tz: string, calIds: string[]) => {
    setTimezone(tz);
    setCalendarIds(calIds);
    setStep("discover");
  };

  const handleOnboardComplete = () => {
    router.push("/dashboard");
  };

  if (step === "setup") {
    return <SetupStage onAdvance={handleSetupComplete} />;
  }

  return (
    <DiscoverStage
      timezone={timezone}
      calendarIds={calendarIds}
      onComplete={handleOnboardComplete}
    />
  );
}
