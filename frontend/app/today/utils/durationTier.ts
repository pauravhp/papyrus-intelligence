export type DurationTier = "sm" | "md" | "lg";

export function durationTier(minutes: number): DurationTier {
  if (minutes <= 20) return "sm";
  if (minutes <= 60) return "md";
  return "lg";
}
