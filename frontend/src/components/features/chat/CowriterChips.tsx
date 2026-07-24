"use client";

import type { Chip } from "@/types/graph";

// Glyphs make the advance / regenerate / wildcard distinction legible at a glance
// — the regenerate icon is the key UX cue ("redo this, don't move on").
const KIND_GLYPH: Record<string, string> = {
  advance: "→",
  regenerate: "↻",
  wildcard: "✦",
};

// The reaction model: three graph-informed chips (advance / regenerate / wildcard)
// in one row, each a reaction to the beat just written. Reaction over composition.
export function CowriterChips({
  chips,
  onSendChip,
  onBranch,
  disabled,
  showBranch = false,
}: {
  chips: Chip[];
  onSendChip: (c: Chip) => void;
  onBranch: () => void;
  disabled?: boolean;
  // The analytic-branch chip is flag-gated: it forks correctly but lands on a
  // generic opener rather than one framed around the piece it branched from, so
  // it's off by default until that UX is finished. See chat/[id]/page.tsx.
  showBranch?: boolean;
}) {
  if (!chips.length) return null;
  return (
    <div className="max-w-4xl mx-auto w-full px-3 sm:px-4 pt-0.5 pb-3 flex flex-wrap items-center gap-2">
      {chips.map((c, i) => (
        <button
          key={i}
          disabled={disabled}
          onClick={() => onSendChip(c)}
          title={c.instruction}
          className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-full text-sm border border-[var(--border)] bg-[var(--surface)] text-[var(--foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors disabled:opacity-50"
        >
          <span className="text-[var(--primary)] font-semibold">{KIND_GLYPH[c.kind] ?? "✦"}</span>
          {c.label}
        </button>
      ))}
      {showBranch && chips.length > 0 && (
        <button
          disabled={disabled}
          onClick={onBranch}
          title="Fork an analytic chat to explore why this lands — shares the same graph."
          className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-full text-sm border border-dashed border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--muted)] transition-colors disabled:opacity-50 ml-auto"
        >
          ↗ Why did that land?
        </button>
      )}
    </div>
  );
}
