"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiClient } from "@/utils/apiClient";
import { BookIcon, PinIcon } from "@/components/ui/Icons";
import type { StorySummary } from "@/types/story";

/**
 * The Library — the retention surface. Compiled pieces
 * (not chat sessions) are the first-class objects: pinned first, then most-recently
 * touched. Each links into its readable document (which can be reopened in the workshop).
 */
export default function LibraryPage() {
  const [stories, setStories] = useState<StorySummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiClient<StorySummary[]>(
          `${process.env.NEXT_PUBLIC_API_URL}/api/v1/stories`,
        );
        setStories(res ?? []);
      } catch {
        setStories([]);
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const sorted = [...stories].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return (b.updated_at || "").localeCompare(a.updated_at || "");
  });

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 pt-16 sm:pt-20 bg-[var(--background)]">
      <div className="max-w-3xl mx-auto w-full">
        <div className="flex items-center gap-2 mb-6">
          <BookIcon className="w-6 h-6 text-[var(--primary)]" />
          <h1 className="text-2xl font-bold text-[var(--foreground)]">Library</h1>
        </div>

        {loaded && sorted.length === 0 && (
          <div className="text-[var(--muted)] text-sm border border-dashed border-[var(--border)] rounded-xl p-8 text-center">
            No pieces yet. Save a piece from a chat and it&apos;ll show up here,
            ready to re-read and continue.
          </div>
        )}

        <ul className="flex flex-col gap-3">
          {sorted.map((s) => (
            <li key={s.id}>
              <Link
                href={`/library/${s.id}`}
                className="flex items-center justify-between gap-3 p-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] hover:border-[var(--primary)] hover:shadow-md transition-all"
              >
                <div className="min-w-0">
                  <div className="font-semibold text-[var(--foreground)] truncate">
                    {s.title || "Untitled piece"}
                  </div>
                  {s.updated_at && (
                    <div className="text-xs text-[var(--muted)] mt-0.5">
                      Updated {new Date(s.updated_at).toLocaleDateString()}
                    </div>
                  )}
                </div>
                {s.pinned && <PinIcon className="w-4 h-4 text-[var(--primary)] shrink-0" />}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
