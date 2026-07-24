"use client";

import { useState, startTransition, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { CloseIcon, GitHubIcon, GoogleIcon, EyeIcon, EyeOffIcon } from "@/components/ui/Icons";
import { loginWithEmail, signUpWithEmail, getOAuthUrl, getUserProfile } from "@/app/actions/auth";
import { useToast } from "@/context/ToastContext";
import { useUser } from "@/context/UserContext";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AuthModal({ isOpen, onClose }: AuthModalProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { showToast } = useToast();
  const { setIsSignedIn, clearSession, setFullName, setAvatar } = useUser();
  
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setEmail("");
      setPassword("");
      setConfirmPassword("");
      setIsSignUp(false);
      setShowPassword(false);
      setIsLoading(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const hasMinLength = password.length >= 10;
  const hasLetter = /[a-zA-Z]/.test(password);
  const hasNumber = /[0-9]/.test(password);
  const hasSymbol = /[^a-zA-Z0-9]/.test(password);
  
  const strengthScore = [hasMinLength, hasLetter, hasNumber, hasSymbol].filter(Boolean).length;
  const passwordsMatch = password === confirmPassword && confirmPassword.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return showToast("Please enter both email and password.", "error");

    if (isSignUp) {
      if (!hasMinLength) return showToast("Password must be at least 10 characters.", "error");
      if (!passwordsMatch) return showToast("Passwords do not match.", "error");
    }

    setIsLoading(true);

    if (isSignUp) {
      const { error } = await signUpWithEmail(email, password);
      if (error) {
        showToast(error, "error");
      } else {
        clearSession();
        showToast("Account created! Check your email to verify.", "success");
        setIsSignUp(false); 
        setPassword("");
        setConfirmPassword("");
      }
    } else {
      const { error } = await loginWithEmail(email, password);
      if (error) {
        showToast(error, "error");
      } else {
        const profile = await getUserProfile();
        if (profile) {
          if (profile.full_name) setFullName(profile.full_name);
          if (profile.avatar_url) setAvatar(profile.avatar_url);
        }

        showToast("Welcome back.", "success");
        setIsSignedIn(true);
        onClose();
      }
    }

    setIsLoading(false);
  };

  const handleOAuth = async (provider: any) => {
    setIsLoading(true);
    const { url, error } = await getOAuthUrl(provider, pathname);
    if (error) {
      showToast(error, "error");
      setIsLoading(false);
    } else if (url) {
      window.location.href = url; 
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity" onClick={onClose}></div>
      
      <div className="relative w-full max-w-md bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-300">
        
        <button onClick={onClose} className="absolute top-4 right-4 p-2 text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--background)] rounded-full transition-all z-10">
          <CloseIcon className="w-5 h-5" />
        </button>

        <div className="p-8 pt-10">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-[var(--foreground)] tracking-tight">
              {isSignUp ? "Create your account" : "Welcome back"}
            </h1>
            <p className="text-sm text-[var(--muted)] mt-2">
              {isSignUp ? "Secure your new semantic profile." : "Enter your credentials to continue."}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-semibold text-[var(--foreground)]">Email address</label>
              <input 
                type="email" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] px-4 py-2.5 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5 relative">
              <div className="flex items-center justify-between">
                <label className="text-sm font-semibold text-[var(--foreground)]">Password</label>
                {!isSignUp && (
                  <button 
                    type="button" 
                    onClick={(e) => { 
                      e.preventDefault();
                      setIsLoading(true); 
                      startTransition(() => {
                        router.push('/auth/forgot-password');
                        onClose();
                      });
                    }} 
                    className="text-xs font-semibold text-[var(--primary)] hover:brightness-110 transition-colors"
                  >
                    Forgot password?
                  </button>
                )}
              </div>
              <div className="relative">
                <input 
                  type={showPassword ? "text" : "password"} 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] px-4 py-2.5 pr-10 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all"
                  required
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOffIcon className="w-4 h-4" /> : <EyeIcon className="w-4 h-4" />}
                </button>
              </div>

              {isSignUp && password.length > 0 && (
                <div className="flex flex-col gap-1 mt-1 animate-in fade-in duration-300">
                  <div className="flex gap-1 h-1.5 w-full">
                    {[1, 2, 3, 4].map((level) => (
                      <div 
                        key={level} 
                        className={`flex-1 rounded-full transition-all duration-300 ${
                          strengthScore >= level 
                            ? (strengthScore <= 2 ? 'bg-amber-500' : 'bg-emerald-500') 
                            : 'bg-[var(--border)]'
                        }`} 
                      />
                    ))}
                  </div>
                  {!hasMinLength && <p className="text-xs text-red-500 mt-1">Password must be at least 10 characters.</p>}
                </div>
              )}
            </div>

            {isSignUp && (
              <div className="flex flex-col gap-1.5 relative animate-in fade-in slide-in-from-top-2 duration-300">
                <label className="text-sm font-semibold text-[var(--foreground)]">Confirm Password</label>
                <div className="relative">
                  <input 
                    type={showPassword ? "text" : "password"} 
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="••••••••"
                    className={`w-full bg-[var(--background)] border text-[var(--foreground)] px-4 py-2.5 pr-10 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--primary)] transition-all ${
                      confirmPassword.length > 0 && !passwordsMatch ? 'border-red-500 focus:ring-red-500' : 'border-[var(--border)]'
                    }`}
                    required
                  />
                </div>
                {confirmPassword.length > 0 && !passwordsMatch && (
                  <p className="text-xs text-red-500 mt-1">Passwords do not match.</p>
                )}
              </div>
            )}

            <button 
              type="submit" 
              disabled={isLoading || (isSignUp && (!hasMinLength || !passwordsMatch))}
              className="w-full mt-2 bg-[var(--primary)] text-[var(--primary-fg)] font-bold py-3 rounded-lg hover:brightness-90 transition-all disabled:opacity-50"
            >
              {isLoading ? "Processing..." : (isSignUp ? "Create Account" : "Sign In")}
            </button>
          </form>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-[var(--border)]"></div>
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-[var(--surface)] px-2 text-[var(--muted)] font-bold tracking-wider">Or continue with</span>
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            <button onClick={() => handleOAuth("google")} disabled={isLoading} className="flex items-center justify-center gap-3 bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] font-semibold py-2.5 rounded-lg hover:bg-[var(--surface)] transition-all disabled:opacity-50">
              <GoogleIcon /> Continue with Google
            </button>
            <button onClick={() => handleOAuth("github")} disabled={isLoading} className="flex items-center justify-center gap-3 bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] font-semibold py-2.5 rounded-lg hover:bg-[var(--surface)] transition-all disabled:opacity-50">
              <GitHubIcon className="w-5 h-5" /> Continue with GitHub
            </button>
          </div>
        </div>

        <div className="bg-[var(--background)] border-t border-[var(--border)] p-4 text-center">
          <p className="text-sm text-[var(--muted)]">
            {isSignUp ? "Already have an account? " : "Don't have an account? "}
            <button 
              type="button"
              onClick={() => {
                setIsSignUp(!isSignUp);
                setPassword("");
                setConfirmPassword("");
              }} 
              className="text-[var(--primary)] font-bold hover:underline transition-all"
            >
              {isSignUp ? "Sign In" : "Sign Up"}
            </button>
          </p>
        </div>

      </div>
    </div>
  );
}