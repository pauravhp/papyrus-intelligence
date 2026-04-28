"use client";

import { useEffect, useState, type CSSProperties } from "react";

interface NumberFieldProps {
  value: number | string;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  fallback?: number;
  style?: CSSProperties;
  ariaLabel?: string;
}

/**
 * Numeric input that lets the user clear the field while editing.
 *
 * type="number" + parseInt(...)||0 traps the user at 0 once they backspace,
 * so we hold a string locally and only parse on blur.
 */
export default function NumberField({
  value,
  onChange,
  min,
  max,
  fallback = 0,
  style,
  ariaLabel,
}: NumberFieldProps) {
  const [local, setLocal] = useState<string>(String(value ?? ""));

  useEffect(() => {
    setLocal(String(value ?? ""));
  }, [value]);

  const commit = () => {
    if (local.trim() === "") {
      onChange(fallback);
      setLocal(String(fallback));
      return;
    }
    let n = parseInt(local, 10);
    if (Number.isNaN(n)) n = fallback;
    if (typeof min === "number" && n < min) n = min;
    if (typeof max === "number" && n > max) n = max;
    onChange(n);
    setLocal(String(n));
  };

  return (
    <input
      type="text"
      inputMode="numeric"
      pattern="[0-9]*"
      value={local}
      aria-label={ariaLabel}
      onChange={(e) => {
        const v = e.target.value.replace(/[^0-9]/g, "");
        setLocal(v);
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          commit();
          (e.target as HTMLInputElement).blur();
        }
      }}
      style={style}
    />
  );
}
