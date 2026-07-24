"use client";

import Link from "next/link";
import { DatabaseIcon, MapIcon, SparkleIcon } from "@/components/ui/Icons";

/**
 * The three ways into the model from the landing page. Every tile points at a
 * real, populated surface — a placeholder tile on the first screen a visitor
 * sees reads as an unfinished product, so there are none.
 */
export function AlternativeNav() {
  return (
    <div className="w-full max-w-3xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-3">
      <Link href="/map" className="flex flex-col items-start p-3.5 bg-[var(--surface)] border border-[var(--border)] rounded-xl hover:border-[var(--primary)] hover:shadow-md transition-all group text-left">
        <MapIcon className="w-5 h-5 text-[var(--muted)] group-hover:text-[var(--primary)] transition-colors mb-2" />
        <h3 className="font-bold text-[var(--foreground)] text-sm mb-0.5">Mind Map</h3>
        <p className="text-xs text-[var(--muted)]">Your concepts, their relations, and the clusters they form.</p>
      </Link>

      <Link href="/understanding" className="flex flex-col items-start p-3.5 bg-[var(--surface)] border border-[var(--border)] rounded-xl hover:border-[var(--primary)] hover:shadow-md transition-all group text-left">
        <SparkleIcon className="w-5 h-5 text-[var(--muted)] group-hover:text-[var(--primary)] transition-colors mb-2" />
        <h3 className="font-bold text-[var(--foreground)] text-sm mb-0.5">Understanding</h3>
        <p className="text-xs text-[var(--muted)]">What the model believes about you — and where you can correct it.</p>
      </Link>

      <Link href="/memory" className="flex flex-col items-start p-3.5 bg-[var(--surface)] border border-[var(--border)] rounded-xl hover:border-[var(--primary)] hover:shadow-md transition-all group text-left">
        <DatabaseIcon className="w-5 h-5 text-[var(--muted)] group-hover:text-[var(--primary)] transition-colors mb-2" />
        <h3 className="font-bold text-[var(--foreground)] text-sm mb-0.5">Memories</h3>
        <p className="text-xs text-[var(--muted)]">The verbatim record every inference is sourced from.</p>
      </Link>
    </div>
  );
}
