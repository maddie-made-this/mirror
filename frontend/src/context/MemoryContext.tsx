"use client";

import React, { createContext, useContext, useState, ReactNode } from "react";
import ReviewModal from "@/components/features/memory/ReviewModal";

interface MemoryContextType {
  triggerMemoryReview: (initialSummary: string, onConfirm: (finalSummary: string) => void) => void;
}

const MemoryContext = createContext<MemoryContextType | undefined>(undefined);

export function MemoryProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const [onConfirmCallback, setOnConfirmCallback] = useState<((s: string) => void) | null>(null);

  const triggerMemoryReview = (initialSummary: string, onConfirm: (finalSummary: string) => void) => {
    setSummary(initialSummary);
    setOnConfirmCallback(() => onConfirm);
    setIsOpen(true);
  };

  const handleConfirm = (finalSummary: string) => {
    if (onConfirmCallback) onConfirmCallback(finalSummary);
    setIsOpen(false);
  };

  return (
    <MemoryContext.Provider value={{ triggerMemoryReview }}>
      {children}
      <ReviewModal 
        isOpen={isOpen} 
        initialSummary={summary} 
        onClose={() => setIsOpen(false)} 
        onConfirm={handleConfirm} 
      />
    </MemoryContext.Provider>
  );
}

export const useMemory = () => {
  const context = useContext(MemoryContext);
  if (!context) throw new Error("useMemory must be used within a MemoryProvider");
  return context;
};