"use client";

import { useState } from "react";
import { AlternativeNav } from "@/components/shared/AlternativeNav";
import { ChevronIcon } from "@/components/ui/Icons";
import { dict } from "@/config";

interface SessionLayoutProps {
  title: string;
  subtitle?: string;
  defaultMode?: string;
  onSessionStart: (mode: string, query: string) => void;
}

export function SessionLayout({
  title,
  subtitle,
  defaultMode = dict.modes.primary.id,
  onSessionStart,
}: SessionLayoutProps) {
  // No upfront mode picker: a single entry point. The session type is a backend
  // tag, not a user choice, so we just carry defaultMode through on start.
  const [inputValue, setInputValue] = useState("");
  const [isTransitioning, setIsTransitioning] = useState(false);

  const handleStart = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    setIsTransitioning(true);

    const footer = document.querySelector("footer");
    if (footer) {
      footer.classList.add("opacity-0", "pointer-events-none", "transition-opacity", "duration-700");
      footer.style.position = "absolute";
      footer.style.bottom = "0";
      footer.style.left = "0";
      footer.style.width = "100%";
      setTimeout(() => footer.classList.add("hidden"), 700);
    }

    setTimeout(() => {
      onSessionStart(defaultMode, inputValue);
    }, 800);
  };

  return (
    <div className="flex flex-col h-full w-full bg-[var(--background)] overflow-hidden relative">

      <div className={`absolute inset-0 flex flex-col justify-between px-4 pt-16 sm:pt-24 pb-12 transition-opacity duration-700 ease-in-out ${isTransitioning ? 'opacity-0 pointer-events-none' : 'opacity-100'} overflow-y-auto`}>

        <div className="flex flex-col items-center w-full max-w-2xl mx-auto shrink-0">
          <h1 className="text-4xl md:text-5xl font-bold text-[var(--foreground)] mb-4 text-center tracking-tight">
            {title}
          </h1>

          {subtitle && (
            <p className="text-base text-[var(--muted)] text-center mb-6 max-w-lg mx-auto">{subtitle}</p>
          )}
        </div>

        <div className="w-full max-w-4xl mx-auto my-12 sm:hidden z-10 shrink-0">
          <form onSubmit={handleStart} className="relative w-full shadow-2xl rounded-2xl">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              disabled={isTransitioning}
              placeholder={isTransitioning ? "Starting session..." : "Start typing to begin your session..."}
              className="w-full bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)] rounded-2xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] py-4 px-5 text-base pr-14 transition-all"
            />
            <button
              type="submit"
              disabled={!inputValue.trim() || isTransitioning}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-[var(--primary)] text-[var(--primary-fg)] rounded-xl hover:brightness-90 disabled:opacity-50 transition-all"
            >
              <ChevronIcon className="w-5 h-5 -rotate-90" />
            </button>
          </form>
        </div>

        <div className="w-full max-w-4xl mx-auto mt-auto pt-8 shrink-0">
           <AlternativeNav />
        </div>
      </div>

      <div className={`hidden sm:flex absolute z-10 inset-x-0 mx-auto w-full transition-all duration-1000 ease-[cubic-bezier(0.25,1,0.5,1)] flex-col ${isTransitioning ? 'bottom-0' : 'bottom-[50%] translate-y-1/2'}`}>

        <div className={`w-full transition-all duration-1000 ease-[cubic-bezier(0.25,1,0.5,1)] flex justify-center ${isTransitioning ? 'bg-[var(--surface)] border-t border-[var(--border)] p-4 shadow-none' : 'bg-transparent border-t-0 border-transparent p-0'}`}>

          <form onSubmit={handleStart} className={`relative mx-auto w-full transition-all duration-1000 flex items-center ${isTransitioning ? 'max-w-4xl gap-3' : 'max-w-3xl gap-0 shadow-2xl rounded-2xl'}`}>

            <div className="relative flex-1 w-full">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                disabled={isTransitioning}
                placeholder={isTransitioning ? "Starting session..." : "Start typing to begin your session..."}
                className={`w-full border border-[var(--border)] text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all duration-1000 ${isTransitioning ? 'bg-[var(--background)] p-3 rounded-lg text-base' : 'bg-[var(--surface)] py-5 px-6 rounded-2xl text-lg pr-14'}`}
              />

              <button
                type="submit"
                disabled={!inputValue.trim() || isTransitioning}
                className={`absolute right-3 top-1/2 -translate-y-1/2 p-2 bg-[var(--primary)] text-[var(--primary-fg)] rounded-xl transition-all duration-500 ${isTransitioning ? 'opacity-0 scale-75 pointer-events-none' : 'opacity-100 hover:brightness-90 disabled:opacity-50'}`}
              >
                <ChevronIcon className="w-5 h-5 -rotate-90" />
              </button>
            </div>

            <button
              type="submit"
              disabled={true}
              className={`bg-[var(--primary)] text-[var(--primary-fg)] rounded-lg font-semibold whitespace-nowrap overflow-hidden transition-all duration-1000 flex items-center justify-center shrink-0 ${isTransitioning ? 'w-[88px] px-6 py-3 opacity-100 opacity-50' : 'w-0 px-0 py-3 opacity-0'}`}
            >
              Send
            </button>
          </form>
        </div>
      </div>

    </div>
  );
}
