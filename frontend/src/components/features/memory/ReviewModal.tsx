"use client";

import { useState, useEffect } from "react";

interface ReviewModalProps {
  isOpen: boolean;
  initialSummary: string;
  onClose: () => void;
  onConfirm: (finalSummary: string) => void;
}

export default function ReviewModal({ isOpen, initialSummary, onClose, onConfirm }: ReviewModalProps) {
  const [summary, setSummary] = useState("");

  useEffect(() => {
    if (isOpen) setSummary(initialSummary);
  }, [isOpen, initialSummary]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-300">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose}></div>
      <div className="relative w-full max-w-2xl bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-300 max-h-[90vh]">
        
        <div className="px-6 py-4 border-b border-[var(--border)] flex justify-between items-center bg-[var(--background)]">
          <h2 className="text-xl font-bold text-[var(--foreground)]">Review Semantic Extraction</h2>
          <button onClick={onClose} className="text-[var(--muted)] hover:text-[var(--foreground)] transition-colors">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-6 h-6"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>
        
        <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-4">
          <p className="text-sm text-[var(--muted)]">Review and edit the extracted semantic memory before finalizing. This is what the AI will reference in the future.</p>
          <textarea 
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            className="w-full h-64 p-4 bg-[var(--background)] border border-[var(--border)] rounded-xl text-[var(--foreground)] text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          />
        </div>

        <div className="px-6 py-4 border-t border-[var(--border)] bg-[var(--background)] flex justify-end gap-3">
          <button onClick={onClose} className="px-5 py-2.5 rounded-lg text-sm font-semibold text-[var(--foreground)] hover:bg-[var(--surface)] border border-[var(--border)] transition-colors">
            Cancel
          </button>
          <button onClick={() => onConfirm(summary)} className="px-5 py-2.5 rounded-lg text-sm font-semibold bg-[var(--primary)] text-[var(--primary-fg)] hover:brightness-90 shadow-sm transition-all">
            Confirm & Save Memory
          </button>
        </div>
      </div>
    </div>
  );
}