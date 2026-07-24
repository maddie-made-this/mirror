"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { updatePassword } from "@/app/actions/auth";
import { useToast } from "@/context/ToastContext";
import { useUser } from "@/context/UserContext";

export default function UpdatePasswordPage() {
  const router = useRouter();
  const { showToast } = useToast();
  const { setIsSignedIn } = useUser();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) return showToast("Please enter a new password.", "error");
    if (password !== confirmPassword) return showToast("Passwords do not match.", "error");
    if (password.length < 10) return showToast("Password must be at least 10 characters.", "error");

    setIsLoading(true);
    const { error } = await updatePassword(password);
    setIsLoading(false);

    if (error) {
      showToast(error, "error");
    } else {
      showToast("Password successfully updated.", "success");
      setIsSignedIn(true); // Automatically log the user in on the client side
      router.push("/");
    }
  };

  const passwordsMatch = password === confirmPassword && confirmPassword.length > 0;

  return (
    <div className="flex-1 w-full h-full flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-xl overflow-hidden p-8 animate-in fade-in zoom-in-95 duration-300">
        
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-[var(--foreground)] tracking-tight">Secure New Password</h1>
          <p className="text-sm text-[var(--muted)] mt-2">Enter your new credentials below.</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-semibold text-[var(--foreground)]">New Password</label>
            <input 
              type="password" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] px-4 py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all"
              required
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-semibold text-[var(--foreground)]">Confirm Password</label>
            <input 
              type="password" 
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••"
              className={`w-full bg-[var(--background)] border text-[var(--foreground)] px-4 py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all ${
                confirmPassword.length > 0 && !passwordsMatch ? 'border-red-500 focus:ring-red-500' : 'border-[var(--border)]'
              }`}
              required
            />
            {confirmPassword.length > 0 && !passwordsMatch && (
              <p className="text-xs text-red-500 mt-1">Passwords do not match.</p>
            )}
          </div>

          <button 
            type="submit" 
            disabled={isLoading || password.length < 10 || !passwordsMatch}
            className="w-full mt-2 bg-[var(--primary)] text-[var(--primary-fg)] font-bold py-3 rounded-lg hover:brightness-90 transition-all disabled:opacity-50"
          >
            {isLoading ? "Updating..." : "Update Password"}
          </button>
        </form>
      </div>
    </div>
  );
}