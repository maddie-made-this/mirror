"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiClient } from "@/utils/apiClient";
import { downloadStory } from "@/utils/exportStory";
import { ArrowLeftIcon, DownloadIcon } from "@/components/ui/Icons";
import type { StoryDetail } from "@/types/story";

/**
 * The story document (product reshape §2.2 / P1.2 + §4.1 P2.2 + §4.3 P1.6). Renders the
 * source conversation's canon beats as a readable document, applies per-beat piece tints
 * from color_map when present, exports to md/txt client-side, and reopens the workshop.
 */
export default function StoryDocumentPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [story, setStory] = useState<StoryDetail | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!id) return;
    (async () => {
      try {
        const res = await apiClient<StoryDetail>(
          `${process.env.NEXT_PUBLIC_API_URL}/api/v1/stories/${id}`,
        );
        setStory(res);
      } catch {
        setStory(null);
      } finally {
        setLoaded(true);
      }
    })();
  }, [id]);

  const tints = story?.color_map?.beat_tints ?? {};

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 pt-16 sm:pt-20 bg-[var(--background)]">
      <div className="max-w-2xl mx-auto w-full">
        <Link
          href="/library"
          className="inline-flex items-center gap-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)] transition-colors mb-4"
        >
          <ArrowLeftIcon className="w-4 h-4" /> Library
        </Link>

        {loaded && !story && (
          <div className="text-[var(--muted)] text-sm">Story not found.</div>
        )}

        {story && (
          <>
            <header className="flex items-start justify-between gap-4 mb-6">
              <h1 className="text-2xl font-bold text-[var(--foreground)]">
                {story.title || "Untitled story"}
              </h1>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => downloadStory(story, "md")}
                  className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-[var(--border)] text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
                  title="Download as Markdown"
                >
                  <DownloadIcon className="w-4 h-4" /> .md
                </button>
                <button
                  onClick={() => downloadStory(story, "txt")}
                  className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-[var(--border)] text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
                  title="Download as plain text"
                >
                  <DownloadIcon className="w-4 h-4" /> .txt
                </button>
              </div>
            </header>

            <article className="flex flex-col gap-4">
              {story.beats.map((beat) => {
                const tint = tints[beat.turn_id];
                return (
                  <p
                    key={beat.turn_id}
                    className="whitespace-pre-wrap leading-relaxed text-[var(--foreground)] rounded-lg px-3 py-2"
                    // P2.2: subtle piece tint from color_map when present; plain otherwise.
                    style={tint ? { backgroundColor: tint } : undefined}
                  >
                    {beat.text}
                  </p>
                );
              })}
              {story.beats.length === 0 && (
                <div className="text-[var(--muted)] text-sm">
                  This story has no canon beats yet.
                </div>
              )}
            </article>

            {/* Reopen the conversation this piece came from. */}
            <Link
              href={`/chat/${story.source_conversation_id}`}
              className="inline-flex items-center gap-1.5 mt-8 text-sm text-[var(--primary)] hover:underline"
            >
              Reopen in chat →
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
