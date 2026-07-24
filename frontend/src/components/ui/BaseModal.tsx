"use client";

import { ReactNode } from "react";

interface BaseModalProps {
  children: ReactNode;
  onClose?: () => void;
  maxWidth?: "sm" | "md" | "lg" | "5xl";
}

export function BaseModal({ children, onClose, maxWidth = "md" }: BaseModalProps) {
  const maxWidthClasses = {
    "sm": "max-w-sm",
    "md": "max-w-md",
    "lg": "max-w-lg",
    "5xl": "max-w-5xl",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-[2px] p-4 sm:p-6 animate-in fade-in duration-200">
      {/* Invisible click-away backdrop */}
      <div className="absolute inset-0" onClick={onClose} />
      
      {/* Modal Content Box */}
      <div className={`relative bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-2xl w-full ${maxWidthClasses[maxWidth]} max-h-[90vh] flex flex-col overflow-hidden scale-100 animate-in zoom-in-95 duration-200 transition-colors duration-500`}>
        {children}
      </div>
    </div>
  );
}