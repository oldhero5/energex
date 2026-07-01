"use client";

import { useState } from "react";

interface Props {
  vintages: string[]; // ISO strings (as_of), oldest → newest
  onChange: (asOf: string | undefined) => void;
}

/**
 * Bitemporal as_of slider.
 *
 * Stops: [vintage[0], ..., vintage[n-1], "latest"]
 * Index 0..n-1 → emit that vintage's as_of ISO
 * Index n      → "latest" → emit undefined (no as_of param)
 *
 * Default: "latest" (rightmost stop).
 */
export function AsOfSlider({ vintages, onChange }: Props) {
  const latestIdx = vintages.length;
  // Default to "latest" (rightmost stop)
  const [idx, setIdx] = useState<number>(latestIdx);

  // With no vintages there's only "latest" — nothing to slide
  if (vintages.length === 0) {
    return (
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted">Knowledge time:</span>
        <span className="num text-accent">latest</span>
      </div>
    );
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const i = Number(e.target.value);
    setIdx(i);
    onChange(i < latestIdx ? vintages[i] : undefined);
  }

  const label = idx < latestIdx ? vintages[idx] : "latest";

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted shrink-0">Knowledge time</span>
      <input
        type="range"
        role="slider"
        min={0}
        max={latestIdx}
        step={1}
        value={idx}
        onChange={handleChange}
        className="w-40 accent-accent cursor-pointer"
        aria-label="as_of knowledge time"
      />
      <span className="num text-xs text-accent min-w-[6ch] text-right">{label}</span>
    </div>
  );
}
