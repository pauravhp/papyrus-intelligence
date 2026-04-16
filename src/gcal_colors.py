"""GCal event color ID ↔ human name mapping.

GCal uses integer string IDs ("1"–"11") for event colors.
This module is the single source of truth for that mapping.
Mirrored on the frontend in frontend/lib/gcalColors.ts.
"""

GCAL_COLOR_NAMES: dict[str, str] = {
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

GCAL_COLOR_IDS: dict[str, str] = {v: k for k, v in GCAL_COLOR_NAMES.items()}
