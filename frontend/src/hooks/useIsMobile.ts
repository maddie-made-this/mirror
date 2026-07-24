"use client";

import { useEffect, useState } from "react";

/**
 * Media-query hook for the mobile/desktop fork. Defaults false on first paint
 * (SSR-safe) and corrects on mount + live on viewport changes.
 */
export function useIsMobile(query = "(max-width: 767px)") {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [query]);
  return isMobile;
}
