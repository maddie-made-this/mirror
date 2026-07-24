"use client";

import { useState } from "react";
import { useUser } from "@/context/UserContext";
import { MindMap } from "@/components/features/map/MindMap";
import { InsightsPanel } from "@/components/features/map/InsightsPanel";
import { MobileMapDrill } from "@/components/features/map/MobileMapDrill";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useProcessing } from "@/hooks/useProcessing";

export default function MapPage() {
  const { userId } = useUser();
  const isMobile = useIsMobile();
  // The map tab shows the MAP first, on every viewport. Mobile used to land on
  // the region drill instead, so tapping "Mind Map" opened a list and the map
  // itself was behind a button — the tab appeared to jump somewhere else. The
  // drill is still one tap away via "☰ Regions".
  const [exploreCanvas, setExploreCanvas] = useState(true);
  // Change 1: quiet indicator for the background extraction worker; it also
  // refetches the graph as new nodes land (within seconds of an utterance).
  const { pending } = useProcessing(userId);

  if (isMobile && !exploreCanvas) {
    return (
      <div className="h-[calc(100dvh-3.5rem)] w-full relative">
        <MobileMapDrill userId={userId} onExplore={() => setExploreCanvas(true)} />
        <ProcessingPill pending={pending} />
      </div>
    );
  }

  return (
    <div className="h-[calc(100dvh-3.5rem)] w-full relative">
      <MindMap userId={userId} />
      <InsightsPanel userId={userId} />
      <ProcessingPill pending={pending} />
      {/* Bottom CENTRE, not top-left: the Insights panel is nearly full-width on
          a phone (w-[calc(100vw-2rem)]) and sat right on top of this. Bottom-16
          is the same rail the legend and Recenter use — clear of the community
          bar pinned to bottom-0 — and the centre slot between them is free. */}
      {isMobile && (
        <button
          onClick={() => setExploreCanvas(false)}
          className="absolute bottom-16 left-1/2 -translate-x-1/2 z-20 px-3 py-1.5 rounded-full text-xs font-bold bg-slate-900/80 backdrop-blur-sm border border-slate-700 text-slate-200"
        >
          ☰ Regions
        </button>
      )}
    </div>
  );
}

/** Quiet "N processing" pill for the background extraction worker (Change 1).
 * Renders nothing when the queue is empty. */
function ProcessingPill({ pending }: { pending: number }) {
  if (pending <= 0) return null;
  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-1.5 rounded-full text-xs bg-slate-900/80 backdrop-blur-sm border border-slate-700 text-slate-300">
      <span className="h-2 w-2 rounded-full bg-sky-400 animate-pulse" />
      {pending} processing
    </div>
  );
}
