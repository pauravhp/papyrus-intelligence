// frontend/lib/gcalColors.ts
/**
 * GCal event color constants and shared ColorRule type.
 * Mirrors src/gcal_colors.py — keep in sync.
 */

export const GCAL_COLOR_NAMES: Record<string, string> = {
  "1": "Lavender",
  "2": "Sage",
  "3": "Grape",
  "4": "Flamingo",
  "5": "Banana",
  "6": "Tangerine",
  "7": "Peacock",
  "8": "Blueberry",
  "9": "Basil",
  "10": "Tomato",
  "11": "Avocado",
}

export const GCAL_COLOR_HEX: Record<string, string> = {
  "1": "#7986cb",
  "2": "#33b679",
  "3": "#8e24aa",
  "4": "#e67c73",
  "5": "#f6c026",
  "6": "#f5511d",
  "7": "#039be5",
  "8": "#3f51b5",
  "9": "#0b8043",
  "10": "#d50000",
  "11": "#8bad45",
}

export const GCAL_COLOR_IDS: Record<string, string> = Object.fromEntries(
  Object.entries(GCAL_COLOR_NAMES).map(([id, name]) => [name, id])
)

export interface ColorRule {
  name: string
  colorId: string | null
  bufferBefore: 0 | 5 | 15 | 30
  bufferAfter: 0 | 5 | 15 | 30
}

export const DEFAULT_CATEGORIES: ColorRule[] = [
  { name: "Meetings & calls", colorId: null, bufferBefore: 15, bufferAfter: 15 },
  { name: "Personal commitments", colorId: null, bufferBefore: 30, bufferAfter: 30 },
]

const VALID_PRESETS = new Set([0, 5, 15, 30])
function clampPreset(n: number): 0 | 5 | 15 | 30 {
  return (VALID_PRESETS.has(n) ? n : 15) as 0 | 5 | 15 | 30
}

export function calendarRulesToCategories(rules: Record<string, unknown>): ColorRule[] {
  return Object.entries(rules).map(([name, rule]) => {
    const r = rule as Record<string, unknown>
    return {
      name,
      colorId: (r.color_id as string | null) ?? null,
      bufferBefore: clampPreset((r.buffer_before_minutes as number) ?? 15),
      bufferAfter: clampPreset((r.buffer_after_minutes as number) ?? 15),
    }
  })
}

export function categoriesToCalendarRules(categories: ColorRule[]): Record<string, unknown> {
  return Object.fromEntries(
    categories.map(cat => [
      cat.name,
      {
        color_id: cat.colorId,
        buffer_before_minutes: cat.bufferBefore,
        buffer_after_minutes: cat.bufferAfter,
        movable: false,
      },
    ])
  )
}

/** Enforce duplicate color constraint: clear colorId on any category that already claims newColorId. */
export function clearDuplicateColor(
  categories: ColorRule[],
  newColorId: string,
  currentIndex: number
): ColorRule[] {
  return categories.map((cat, i) =>
    i !== currentIndex && cat.colorId === newColorId
      ? { ...cat, colorId: null }
      : cat
  )
}

export const NAME_REGEX = /^[a-zA-Z0-9 &'()\-,.]*$/
export const NAME_MAX_LENGTH = 32
