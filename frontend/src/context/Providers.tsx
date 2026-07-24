"use client";

import { ThemeProvider } from "@/context/ThemeContext";
import { UserProvider } from "@/context/UserContext";
import { ToastProvider } from "@/context/ToastContext";
import { MemoryProvider } from "@/context/MemoryContext";
import { ReactNode } from "react";

export function GlobalProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <UserProvider>
        <ToastProvider>
          <MemoryProvider>
            {children}
          </MemoryProvider>
        </ToastProvider>
      </UserProvider>
    </ThemeProvider>
  );
}