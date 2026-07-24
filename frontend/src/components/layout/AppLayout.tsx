"use client";

import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import Footer from "@/components/layout/Footer";
import { AuthModal } from "@/components/shared/AuthModal";
import { DebugPanel } from "@/components/features/dev/DebugPanel";

// Routes that require a signed-in session. Any path that starts with one of
// these prefixes will redirect to "/" and open the auth modal if not signed in.
const PROTECTED_PREFIXES = ["/chat", "/memory", "/map", "/settings", "/library", "/understanding"];

export default function AppLayout({ children, defaultCollapsed }: { children: React.ReactNode; defaultCollapsed: boolean; }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(defaultCollapsed);
  const pathname = usePathname();
  const router = useRouter();

  const { isSignedIn, authReady, isAuthModalOpen, setIsAuthModalOpen, isDev } = useUser();

  const isProtected = PROTECTED_PREFIXES.some(prefix => pathname.startsWith(prefix));

  // Gate protected routes — but only once the session has actually resolved.
  // On a hard load isSignedIn is transiently false until getSession() returns;
  // acting before authReady would bounce a signed-in user to the login modal.
  useEffect(() => {
    if (authReady && isProtected && !isSignedIn) {
      router.replace("/");
      setIsAuthModalOpen(true);
    }
  }, [pathname, isSignedIn, authReady, isProtected, router, setIsAuthModalOpen]);

  // Check if the current URL is a chat session, explicitly excluding the archive page.
  const isChatSession = pathname.startsWith("/chat/") && pathname !== "/chat" && pathname !== "/chat/archive";

  const toggleSidebar = () => {
    setIsSidebarCollapsed((prev) => {
      const newState = !prev;
      document.cookie = `sidebarCollapsed=${newState}; path=/; max-age=31536000`;
      return newState;
    });
  };

  return (
    <div className="flex h-[100dvh] w-full bg-transparent overflow-hidden transition-colors duration-500">
      <Sidebar
        isSidebarCollapsed={isSidebarCollapsed}
        toggleSidebar={toggleSidebar}
        isMobileMenuOpen={isMobileMenuOpen}
        setIsMobileMenuOpen={setIsMobileMenuOpen}
      />

      <div className="flex-1 flex flex-col relative min-w-0 bg-transparent transition-colors duration-500">
        <Header
          isSidebarCollapsed={isSidebarCollapsed}
          setIsMobileMenuOpen={setIsMobileMenuOpen}
        />

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col overflow-y-auto overflow-x-hidden relative">

          <div className="flex-1 flex flex-col">
            {/* On protected routes, hold content until auth resolves so we don't
                flash protected UI or fire fetches with a null user. */}
            {isProtected && !authReady ? null : children}
          </div>

          {/* Conditional Footer: Renders everywhere EXCEPT inside chat sessions */}
          {!isChatSession && <Footer />}
          {/* Debug panel can surface prompt internals — gated on the server-owned
              profiles.is_dev flag, so it never renders for a normal user. */}
          {isDev && <DebugPanel />}
        </main>
      </div>

      {/* Global Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
      />
    </div>
  );
}
