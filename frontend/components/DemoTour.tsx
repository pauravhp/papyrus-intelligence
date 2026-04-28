"use client";

import { driver, type AllowedButtons, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import { useEffect, useRef } from "react";
import { TOUR_COPY, SKIP_LABEL, type TourStep } from "./demoTourCopy";

type Props = {
  step: TourStep | null;
  anchor: string | null;       // CSS selector or null for centered popover
  variables?: Record<string, string | number>;
  onSkip: () => void;
};

function fill(template: string, vars: Record<string, string | number> | undefined): string {
  if (!vars) return template;
  return Object.entries(vars).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    template,
  );
}

export default function DemoTour({ step, anchor, variables, onSkip }: Props) {
  const driverRef = useRef<Driver | null>(null);

  useEffect(() => {
    if (!step) {
      driverRef.current?.destroy();
      driverRef.current = null;
      return;
    }
    const copy = TOUR_COPY[step];
    const popoverConfig = {
      title: copy.title,
      description: fill(copy.body, variables),
      showButtons: ["close"] as AllowedButtons[],
      // Driver.js v1.x has no closeBtnText on Popover — set text via onPopoverRender
      onPopoverRender: (popover: { closeButton: HTMLButtonElement }) => {
        popover.closeButton.textContent = SKIP_LABEL;
      },
    };

    const d = driver({
      showProgress: false,
      animate: true,
      onCloseClick: () => {
        d.destroy();
        onSkip();
      },
    });
    driverRef.current = d;

    if (anchor) {
      d.highlight({ element: anchor, popover: popoverConfig });
    } else {
      d.highlight({ popover: popoverConfig } as any);
    }

    return () => {
      d.destroy();
    };
  }, [step, anchor, variables, onSkip]);

  return null;
}
