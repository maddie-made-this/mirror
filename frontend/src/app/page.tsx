"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { SessionLayout } from "@/components/shared/SessionLayout";
import { SampleGraphSection } from "@/components/features/map/SampleGraphSection";
import { dict } from "@/config";

export default function UnifiedHomePage() {
  const router = useRouter();
  const { hasCompletedOnboarding, setHasCompletedOnboarding } = useUser();
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // No upfront mode choice: the user just types and starts. The first ever
  // session is onboarding; everything after defaults to the primary type
  // (session_type remains a backend tag, no longer a user-selected mode).
  const handleStart = (_mode: string, query: string) => {
    const encodedMessage = encodeURIComponent(query);
    const type = hasCompletedOnboarding ? dict.modes.primary.id : "onboarding";
    if (!hasCompletedOnboarding) setHasCompletedOnboarding(true);
    // Mint the conversation id up front and go straight to the single chat page —
    // there is no /chat/new. The chat row only materializes on the first turn.
    const id = crypto.randomUUID();
    router.push(`/chat/${id}?type=${type}&q=${encodedMessage}`);
  };

  if (!isMounted) return null;

  return (
    <>
      {/* MUST be a full viewport (minus the h-14 header). SessionLayout animates the
          composer to `bottom-0` of THIS container on submit — shortening it to make
          the section below peek left the composer stranding partway up the screen
          instead of docking at the bottom. Discoverability is handled by the scroll
          cue below, not by shrinking the hero. */}
      <div className="relative h-[calc(100vh-3.5rem)] shrink-0">
        <SessionLayout
          title={dict.home.title}
          subtitle={dict.home.subtitle}
          defaultMode={dict.modes.primary.id}
          onSessionStart={handleStart}
        />
        <a
          href="#sample-model"
          /* z below the composer (z-10): when the composer animates down and docks
             at bottom-0 it covers this cue, instead of the cue floating over it. */
          className="absolute bottom-1 left-1/2 -translate-x-1/2 z-[5] flex items-center gap-1.5 text-[11px] text-[var(--muted)] hover:text-[var(--foreground)] transition-colors px-3 py-1.5"
        >
          See a sample model
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5 animate-bounce">
            <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </a>
      </div>
      <SampleGraphSection />
    </>
  );
}