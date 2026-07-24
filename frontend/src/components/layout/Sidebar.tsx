"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type MouseEvent } from "react";
import {
  MirrorMark, MenuIcon, PlusIcon, HomeIcon, ChatIcon, DatabaseIcon, BrainIcon, MapIcon,
  SignOutIcon, SignInIcon, CloseIcon,
  CogIcon, BookIcon
} from "@/components/ui/Icons";
import { useUser } from "@/context/UserContext";
import { dict } from "@/config";

// ... (SidebarProps, NavDivider, and NavItem code remain unchanged) ...
interface SidebarProps {
  isSidebarCollapsed: boolean;
  toggleSidebar: () => void;
  isMobileMenuOpen: boolean;
  setIsMobileMenuOpen: (val: boolean) => void;
}

function NavDivider() {
  return <div className="h-px bg-[var(--sidebar-border)] my-2 mx-3 shrink-0 transition-colors duration-500"></div>;
}

// Routes reachable while signed out — just the landing page. Everything else is
// gated in the sidebar itself (see guardedNav) so a signed-out click never starts
// a navigation, which is what keeps the auth modal from flashing a half-rendered page.
const PUBLIC_ROUTES = new Set<string>(["/"]);

function NavItem({ icon: Icon, label, href, collapsed = false, isPrimary = false, isActive = false, onClick }: any) {
  const className = `flex items-center px-3 py-3 w-full rounded-lg transition-all duration-500 text-left ${
    isPrimary 
      ? "bg-[var(--primary)] hover:brightness-90 text-[var(--primary-fg)] font-semibold" 
      : isActive
      ? "bg-[var(--sidebar-hover)] brightness-[1.25] text-[var(--sidebar-fg)] shadow-sm font-medium"
      : "hover:bg-[var(--sidebar-hover)] text-[var(--sidebar-muted)] hover:text-[var(--sidebar-fg)]"
  }`;

  const content = (
    <>
      <div className="w-6 h-6 flex items-center justify-center shrink-0">
        <Icon className="w-5 h-5" />
      </div>
      <div className={`ml-2.5 overflow-hidden transition-opacity duration-300 ${collapsed ? "opacity-0 pointer-events-none" : "opacity-100"}`}>
        <div className="w-[150px] whitespace-nowrap">{label}</div>
      </div>
    </>
  );

  if (href) {
    return <Link href={href} onClick={onClick} className={className}>{content}</Link>;
  }

  return <button onClick={onClick} className={className}>{content}</button>;
}

export default function Sidebar({ isSidebarCollapsed, toggleSidebar, isMobileMenuOpen, setIsMobileMenuOpen }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { isSignedIn, setIsAuthModalOpen, performLogOut } = useUser();

  const closeMobileMenu = () => {
    setIsMobileMenuOpen(false);
  };

  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [pathname, setIsMobileMenuOpen]);

  // Auth gate for every navigating item. Signed out + a gated route => cancel the
  // <Link> navigation and open the modal in the SAME click. Doing it here (rather
  // than letting each destination page self-check after mount) is what removes the
  // flash of a half-rendered page before the modal appears, and makes every gated
  // icon behave identically instead of only the pages that happened to self-check.
  const guardedNav = (href?: string, isMobile = false) => (e: MouseEvent) => {
    const blocked = !!href && !PUBLIC_ROUTES.has(href) && !isSignedIn;
    // Cancel the navigation BEFORE it starts — this is the jitter fix.
    if (blocked) e.preventDefault();
    // Close the drawer either way, so on mobile the modal isn't hidden behind it.
    if (isMobile) closeMobileMenu();
    if (blocked) setIsAuthModalOpen(true);
  };

  // Single entry: New Chat starts a chat directly — no mode picker (6B).
  const handleNewChat = () => {
    if (!isSignedIn) {
      setIsAuthModalOpen(true);
      return;
    }
    setIsMobileMenuOpen(false);
    // Mint the id and go straight to the single chat page (no /chat/new).
    router.push(`/chat/${crypto.randomUUID()}?type=${dict.modes.primary.id}`);
  };

  const renderPrimaryNav = (isMobile = false) => {
    const collapsed = !isMobile && isSidebarCollapsed;
    const isHomeActive = pathname === "/" || pathname === "/hub";
    
    return (
      <>
        <NavItem
          icon={PlusIcon}
          label="New Chat"
          collapsed={collapsed}
          isPrimary={true}
          onClick={() => {
            if (isMobile) closeMobileMenu();
            handleNewChat();
          }}
        />

        <NavDivider />
        
        <NavItem icon={HomeIcon} label="Home" href="/" collapsed={collapsed} isActive={isHomeActive} onClick={guardedNav("/", isMobile)} />
        <NavItem icon={ChatIcon} label="Chats" href="/chat" collapsed={collapsed} isActive={pathname.startsWith("/chat")} onClick={guardedNav("/chat", isMobile)} />
        <NavItem icon={MapIcon} label="Mind Map" href="/map" collapsed={collapsed} isActive={pathname.startsWith("/map")} onClick={guardedNav("/map", isMobile)} />
        <NavItem icon={BrainIcon} label="Understanding" href="/understanding" collapsed={collapsed} isActive={pathname.startsWith("/understanding")} onClick={guardedNav("/understanding", isMobile)} />
        <NavItem icon={DatabaseIcon} label="Memories" href="/memory" collapsed={collapsed} isActive={pathname === "/memory"} onClick={guardedNav("/memory", isMobile)} />
        <NavItem icon={BookIcon} label="Library" href="/library" collapsed={collapsed} isActive={pathname.startsWith("/library")} onClick={guardedNav("/library", isMobile)} />
      </>
    );
  };

  const renderBottomNav = (isMobile = false) => {
    const collapsed = !isMobile && isSidebarCollapsed;
    return (
      <div className="flex flex-col gap-1 w-full">
        <NavItem icon={CogIcon} label="Settings" href="/settings" collapsed={collapsed} isActive={pathname.startsWith("/settings")} onClick={guardedNav("/settings", isMobile)} />
        
        {isSignedIn ? (
          <button 
            onClick={() => performLogOut()} 
            className="flex items-center px-3 py-3 w-full rounded-lg transition-all duration-500 text-left border border-[var(--sidebar-border)] text-[var(--sidebar-muted)] hover:text-[var(--sidebar-fg)] hover:bg-[var(--sidebar-hover)] mt-2"
          >
            <div className="w-6 h-6 flex items-center justify-center shrink-0">
              <SignOutIcon className="w-5 h-5" />
            </div>
            <div className={`ml-2.5 overflow-hidden transition-opacity duration-300 ${collapsed ? "opacity-0 pointer-events-none" : "opacity-100"}`}>
              <div className="w-[150px] whitespace-nowrap">Sign Out</div>
            </div>
          </button>
        ) : (
          <button 
            type="button"
            onClick={() => {
              if (isMobile) closeMobileMenu();
              setIsAuthModalOpen(true);
            }}
            className="flex items-center px-3 py-3 w-full rounded-lg transition-all duration-500 text-left border border-[var(--sidebar-border)] text-[var(--sidebar-muted)] hover:text-[var(--sidebar-fg)] hover:bg-[var(--sidebar-hover)] mt-2"
          >
            <div className="w-6 h-6 flex items-center justify-center shrink-0">
              <SignInIcon className="w-5 h-5" />
            </div>
            <div className={`ml-2.5 overflow-hidden transition-opacity duration-300 ${collapsed ? "opacity-0 pointer-events-none" : "opacity-100"}`}>
              <div className="w-[150px] whitespace-nowrap">Sign In</div>
            </div>
          </button>
        )}
        
      </div>
    );
  };

  return (
    <>
      <aside className={`hidden md:flex flex-col bg-[var(--sidebar-bg)] text-[var(--sidebar-fg)] shrink-0 overflow-visible transition-all duration-500 z-20 md:border-r border-[var(--sidebar-border)] ${isSidebarCollapsed ? "w-16" : "w-64"}`}>
        <div className="h-16 flex items-center shrink-0 w-full px-4 overflow-hidden">
          <Link href="/" className={`flex items-center overflow-hidden transition-all duration-300 ${isSidebarCollapsed ? "w-0 opacity-0" : "w-full opacity-100 hover:opacity-80"}`}>
            <MirrorMark className="w-6 h-6 rounded shrink-0" />
            <h1 className="ml-3 text-xl font-bold whitespace-nowrap">Mirror AI</h1>
          </Link>
          <button onClick={toggleSidebar} className={`p-1.5 hover:bg-[var(--sidebar-hover)] text-[var(--sidebar-muted)] hover:text-[var(--sidebar-fg)] rounded-md shrink-0 transition-all duration-500 ${isSidebarCollapsed ? "mx-auto" : "ml-auto"}`}>
            <MenuIcon className="w-6 h-6" />
          </button>
        </div>

        <nav className="flex-1 flex flex-col gap-1 p-2 relative">
          {renderPrimaryNav()}
        </nav>
        
        <div className="mt-auto flex flex-col p-2 overflow-x-hidden transition-colors duration-500">
          <NavDivider />
          {renderBottomNav()}
        </div>
      </aside>

      <div className={`fixed inset-0 z-50 flex md:hidden transition-all duration-300 ${isMobileMenuOpen ? "visible" : "invisible delay-300"}`}>
        <div 
          className={`absolute inset-0 bg-black/50 transition-opacity duration-300 ${isMobileMenuOpen ? "opacity-100" : "opacity-0"}`} 
          onClick={closeMobileMenu}
        ></div>
        
        <div className={`relative w-64 bg-[var(--sidebar-bg)] text-[var(--sidebar-fg)] flex flex-col shadow-xl h-full overflow-visible transition-transform duration-300 ${isMobileMenuOpen ? "translate-x-0" : "-translate-x-full"}`}>
          <div className="px-5 h-16 flex items-center justify-between shrink-0 border-b border-[var(--sidebar-border)]">
            <Link href="/" onClick={closeMobileMenu} className="flex items-center overflow-hidden hover:opacity-80 transition-opacity">
              <MirrorMark className="w-6 h-6 rounded shrink-0" />
              <h1 className="ml-3 text-xl font-bold whitespace-nowrap">Mirror AI</h1>
            </Link>
            <button onClick={closeMobileMenu} className="p-1.5 text-[var(--sidebar-muted)] hover:text-[var(--sidebar-fg)] rounded-md transition-colors duration-500">
              <CloseIcon className="w-6 h-6" />
            </button>
          </div>
          
          <nav className="flex-1 flex flex-col gap-1 p-2 relative overflow-y-auto">
            {renderPrimaryNav(true)}
          </nav>
          
          <div className="mt-auto flex flex-col p-2 transition-colors duration-500">
            <NavDivider />
            {renderBottomNav(true)}
          </div>
        </div>
      </div>
    </>
  );
}
