"use client";

import Link from "next/link";
import { CloseIcon } from "@/components/ui/Icons";
import { useUser } from "@/context/UserContext";

export default function AuthErrorPage() {
  const { setIsAuthModalOpen } = useUser();

  return (
    <div className="flex-1 w-full h-full flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md bg-[var(--surface)] border border-red-500/20 rounded-2xl shadow-xl overflow-hidden p-8 text-center animate-in fade-in zoom-in-95 duration-300">
        
        <div className="w-12 h-12 bg-red-500/10 text-red-500 rounded-full flex items-center justify-center mx-auto mb-4">
          <CloseIcon className="w-6 h-6" />
        </div>

        <h1 className="text-2xl font-bold text-[var(--foreground)] tracking-tight mb-2">Authentication Failed</h1>
        <p className="text-sm text-[var(--muted)] mb-8">
          The security link may have expired, or the authentication provider rejected the request. Please try again.
        </p>

        <div className="flex flex-col gap-3">
          <button 
            onClick={() => setIsAuthModalOpen(true)}
            className="w-full bg-[var(--primary)] text-[var(--primary-fg)] font-bold py-3 rounded-lg hover:brightness-90 transition-all"
          >
            Open Login
          </button>
          <Link 
            href="/"
            className="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] font-bold py-3 rounded-lg hover:bg-[var(--sidebar-hover)] transition-all"
          >
            Return Home
          </Link>
        </div>
      </div>
    </div>
  );
}