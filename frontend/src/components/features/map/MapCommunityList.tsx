"use client";

import { useState } from "react";
import { clusterColor } from "./mapHelpers";
import type { ClusterInfo } from "@/types/graph";

// §10 — mobile representation. Pinch-panning a force graph on a phone is
// miserable, so on narrow viewports we offer a collapsible, tappable index of
// communities. Tapping one flies the map to that community (centre + zoom), which
// is the one interaction that actually matters on a small screen. Desktop keeps
// the full canvas (this whole control is md:hidden).
export function MapCommunityList({
  clusters,
  onFocus,
}: {
  clusters: ClusterInfo[];
  onFocus: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!clusters.length) return null;
  const sorted = [...clusters].sort((a, b) => b.size - a.size);

  return (
    <div className="md:hidden fixed inset-x-0 bottom-0 z-30 border-t border-slate-700 bg-slate-900/95 backdrop-blur">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left"
      >
        <span className="text-sm font-semibold text-slate-200">
          Communities <span className="text-slate-500">({clusters.length})</span>
        </span>
        <span className="text-xs text-slate-500">{open ? "▾ hide" : "▸ browse"}</span>
      </button>

      {open && (
        <ul className="max-h-[45vh] overflow-y-auto pb-[env(safe-area-inset-bottom)]">
          {sorted.map((c, ci) => (
            <li key={c.id}>
              <button
                onClick={() => {
                  onFocus(c.id);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-3 border-t border-slate-800 px-4 py-2.5 text-left active:bg-slate-800"
              >
                <span
                  className="h-3 w-3 shrink-0 rounded-full"
                  style={{ background: clusterColor(c.id, ci) }}
                />
                <span className="flex-1 truncate text-sm text-slate-200">{c.label}</span>
                <span className="text-xs text-slate-500">{c.size}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
