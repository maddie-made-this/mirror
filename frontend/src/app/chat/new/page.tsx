"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * Retired route. `chat/new` was merged into the single `chat/[id]` page; this stub
 * stays only as a safety net so any stray link/bookmark to /chat/new still works —
 * it mints a fresh conversation id and replaces into /chat/<uuid>, preserving the
 * query (type/q/cowriter). `replace` (not push) leaves no /chat/new history entry.
 */
function NewChatRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const qs = searchParams.toString();
    router.replace(`/chat/${crypto.randomUUID()}${qs ? `?${qs}` : ""}`);
  }, [router, searchParams]);

  return <div className="flex-1 w-full h-full bg-[var(--background)]" />;
}

export default function NewChatPage() {
  return (
    <Suspense fallback={<div className="flex-1 w-full h-full bg-[var(--background)]" />}>
      <NewChatRedirect />
    </Suspense>
  );
}
