"use client";

import { useRef, useCallback, useState, useEffect } from "react";

export function useLongPress(onLongPress: () => void, ms: number = 500) {
  const [isTouch, setIsTouch] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    setIsTouch(typeof window !== "undefined" && window.matchMedia('(pointer: coarse)').matches);
  }, []);

  const startPress = useCallback(() => {
    if (!isTouch) return;
    timerRef.current = setTimeout(() => {
      if (typeof window !== "undefined" && window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(50);
      }
      onLongPress();
    }, ms);
  }, [onLongPress, ms, isTouch]);

  const clearPress = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  return {
    isTouch,
    handlers: {
      onTouchStart: startPress,
      onTouchEnd: clearPress,
      onTouchMove: clearPress,
      onContextMenu: (e: React.MouseEvent) => { if (isTouch) e.preventDefault(); }
    }
  };
}