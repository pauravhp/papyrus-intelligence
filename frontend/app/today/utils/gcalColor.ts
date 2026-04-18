function hexToHue(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;

  if (d === 0) return 0;

  let h = 0;
  switch (max) {
    case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
    case g: h = ((b - r) / d + 2) / 6; break;
    case b: h = ((r - g) / d + 4) / 6; break;
  }
  return Math.round(h * 360);
}

const FALLBACK = {
  border: "rgba(44,26,14,0.25)",
  fill: "rgba(44,26,14,0.05)",
};

export function gcalColorToPapyrus(hex: string): { border: string; fill: string } {
  if (!hex || !hex.startsWith("#") || hex.length !== 7) return FALLBACK;

  const h = hexToHue(hex);
  return {
    border: `hsl(${h}, 35%, 38%)`,
    fill: `hsl(${h}, 30%, 88%)`,
  };
}
