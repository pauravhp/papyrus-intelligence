// frontend/app/onboard/page.tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import SetupStage from "./SetupStage";
import DiscoverStage from "./DiscoverStage";
import ImportStage from "./ImportStage";
import type { Variant } from "./ImportStage";
import type { CommitResponse } from "@/lib/migrationApi";

type Step = "setup" | "discover" | "import";

// TODO: v2 threshold gate — see brief §4 for labels_only_card and skip_entirely variants.
function determineImportVariant(): Variant {
  return "paste";
}

export default function OnboardPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("setup");
  const [timezone, setTimezone] = useState("UTC");
  const [calendarIds, setCalendarIds] = useState<string[]>([]);
  const [importVariant, setImportVariant] = useState<Variant>("paste");

  const handleSetupComplete = (tz: string, calIds: string[]) => {
    setTimezone(tz);
    setCalendarIds(calIds);
    setStep("discover");
  };

  const handleDiscoverComplete = () => {
    setImportVariant(determineImportVariant());
    setStep("import");
  };

  // Task 13 will replace this with the demo-steps flow.
  const handleImportContinue = (_result: CommitResponse) => {
    router.push("/today");
  };

  if (step === "setup") {
    return <SetupStage onAdvance={handleSetupComplete} />;
  }

  if (step === "discover") {
    return (
      <DiscoverStage
        timezone={timezone}
        calendarIds={calendarIds}
        onComplete={handleDiscoverComplete}
      />
    );
  }

  return (
    <ImportStage
      variant={importVariant}
      onComplete={() => router.push("/today")}
      onContinueToDemoSteps={handleImportContinue}
    />
  );
}
