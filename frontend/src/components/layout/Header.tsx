"use client";

import Link from "next/link";
import { MirrorMark, MenuIcon, SignInIcon, ThemeIcon, SparkleIcon } from "../ui/Icons";
import { useTheme } from "@/context/ThemeContext";
import { useUser } from "@/context/UserContext";

interface HeaderProps {
  isSidebarCollapsed: boolean;
  setIsMobileMenuOpen: (val: boolean) => void;
}

export default function Header({ isSidebarCollapsed, setIsMobileMenuOpen }: HeaderProps) {
  const { openThemeModal } = useTheme();
  
  // Consuming the updated UserContext variables
  const { avatar, isSignedIn, fullName, setIsAuthModalOpen } = useUser();

  return (
    <header id="main-header" className="flex justify-between items-center px-2 sm:px-4 py-2 shrink-0 h-14 bg-[var(--header-bg)] border-b border-[var(--header-border)] md:border-none z-10 transition-colors duration-500 w-full">
      
      {/* Left Group: Menu & Logo */}
      <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
        <button 
          onClick={() => setIsMobileMenuOpen(true)} 
          className="md:hidden p-2 -ml-1 text-[var(--logo-color)] hover:opacity-80 rounded-md transition-colors duration-500"
        >
          <MenuIcon className="w-6 h-6" />
        </button>

        <Link href="/" className={`flex items-center gap-2 sm:gap-3 transition-opacity hover:opacity-80 ${!isSidebarCollapsed ? "md:hidden" : "animate-in fade-in duration-300"}`}>
          <MirrorMark className="w-8 h-8 rounded-md shadow-sm shrink-0" />
          <h1 className="text-xl font-bold hidden sm:block whitespace-nowrap text-[var(--logo-color)] transition-colors duration-500">
            Mirror AI
          </h1>
        </Link>
      </div>
      
      {/* Right Group: Actions */}
      <div className="flex items-center gap-1.5 sm:gap-4 shrink-0">
        
        {/* Theme Button */}
        <button 
          onClick={openThemeModal} 
          className="w-9 h-9 sm:w-9 sm:h-9 rounded-full bg-[var(--surface)] flex items-center justify-center border border-[var(--border)] hover:bg-[var(--sidebar-hover)] transition-colors shadow-sm shrink-0 duration-500"
          aria-label="Change Theme"
        >
          <ThemeIcon className="w-5 h-5 text-[var(--foreground)]" />
        </button>

        {/* Auth/Profile */}
        {isSignedIn ? (
          <div className="flex items-center gap-2 sm:gap-3">
            <Link href="/settings" className="w-9 h-9 sm:w-9 sm:h-9 rounded-full bg-[var(--surface)] flex items-center justify-center border border-[var(--border)] hover:bg-[var(--sidebar-hover)] transition-colors shadow-sm shrink-0 duration-500 overflow-hidden font-bold text-[var(--foreground)]">
              {avatar ? (
                <img src={avatar} alt="User Avatar" className="w-full h-full object-cover" />
              ) : (
                fullName?.trim() ? fullName.trim().charAt(0).toUpperCase() : "U"
              )}
            </Link>
          </div>
        ) : (
          <button 
            onClick={() => setIsAuthModalOpen(true)} 
            className="flex items-center justify-center gap-1.5 bg-[var(--primary)] text-[var(--primary-fg)] px-3 py-1.5 sm:px-4 rounded-lg text-sm font-semibold hover:brightness-90 transition-all shadow-sm shrink-0"
            >
            <SignInIcon className="w-5 h-5" />
            <span className="whitespace-nowrap">Sign In</span>
          </button>
        )}
      </div>

    </header>
  );
}