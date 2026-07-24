"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftIcon } from "@/components/ui/Icons";
import { resetPassword } from "@/app/actions/auth";
import { useToast } from "@/context/ToastContext";

export default function ForgotPasswordPage() {
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return showToast("Please enter your email.", "error");

    setIsLoading(true);
    const { error } = await resetPassword(email);
    setIsLoading(false);

    if (error) {
      showToast(error, "error");
    } else {
      setIsSubmitted(true);
    }
  };

  return (
    <div className="flex-1 w-full h-full flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-xl overflow-hidden p-8 animate-in fade-in zoom-in-95 duration-300 relative">
        
        <Link href="/" className="absolute top-4 left-4 p-2 text-[var(--muted)] hover:text-[var(--foreground)] transition-colors">
          <ArrowLeftIcon className="w-5 h-5" />
        </Link>

        <div className="text-center mb-8 mt-4">
          <h1 className="text-2xl font-bold text-[var(--foreground)] tracking-tight">Reset Password</h1>
          <p className="text-sm text-[var(--muted)] mt-2">
            {isSubmitted ? "Check your inbox for the next steps." : "Enter your email to receive a secure reset link."}
          </p>
        </div>

        {isSubmitted ? (
          <div className="bg-[var(--background)] border border-[var(--border)] p-4 rounded-lg text-center">
            <p className="text-sm font-semibold text-[var(--primary)] mb-2">Email sent to {email}</p>
            <p className="text-xs text-[var(--muted)]">If an account exists, a link will arrive shortly. You can close this page.</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-semibold text-[var(--foreground)]">Email address</label>
              <input 
                type="email" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] px-4 py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all"
                required
              />
            </div>
            <button 
              type="submit" 
              disabled={isLoading}
              className="w-full mt-2 bg-[var(--primary)] text-[var(--primary-fg)] font-bold py-3 rounded-lg hover:brightness-90 transition-all disabled:opacity-50"
            >
              {isLoading ? "Sending..." : "Send Reset Link"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}