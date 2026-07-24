"use client";

import React, { createContext, useContext, useEffect, useRef, useCallback } from "react";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { getUserProfile, logOut } from "@/app/actions/auth";
import { createClient } from "@/utils/supabase/client";
import { apiClient } from "@/utils/apiClient";
import { dict } from "@/config";

export interface UserSettings {
  enterToSend: boolean;
  memoryPaused: boolean;
  selectedModel: string;
  selectedLanguage: string;
}

export const DEFAULT_SETTINGS: UserSettings = {
  enterToSend: true,
  memoryPaused: false,
  selectedModel: "",
  selectedLanguage: "English",
};

interface UserContextType {
  avatar: string | null;
  setAvatar: (val: string | null) => void;
  isSignedIn: boolean;
  setIsSignedIn: (val: boolean) => void;
  // False until the Supabase session has resolved at least once. Consumers must
  // wait for this before treating !isSignedIn as "signed out" — on a hard load
  // isSignedIn is transiently false until getSession() returns.
  authReady: boolean;
  userId: string | null;
  fullName: string;
  setFullName: (val: string) => void;
  // Server-owned debug flag (profiles.is_dev via GET /account/me). Gates the debug
  // panel, which can surface prompt internals. Deliberately NOT persisted to
  // localStorage — it re-derives from the server on every load so it can't be
  // flipped on by editing client storage.
  isDev: boolean;
  hasCompletedOnboarding: boolean;
  setHasCompletedOnboarding: (val: boolean) => void;
  settings: UserSettings;
  updateLocalSetting: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
  isAuthModalOpen: boolean;
  setIsAuthModalOpen: (val: boolean) => void;
  clearSession: () => void;
  performLogOut: () => Promise<void>;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [avatar, setAvatar] = useLocalStorage<string | null>("mirror_avatar", null);
  const [isSignedIn, setIsSignedIn] = useLocalStorage<boolean>("mirror_signed_in", false);
  const [fullName, setFullName] = useLocalStorage<string>("mirror_fullname", "User");
  const [hasCompletedOnboarding, setHasCompletedOnboarding] = useLocalStorage<boolean>("mirror_onboarded", false);
  const [settings, setSettings] = useLocalStorage<UserSettings>("mirror_settings", DEFAULT_SETTINGS);

  const updateLocalSetting = <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const [isAuthModalOpen, setIsAuthModalOpen] = React.useState<boolean>(false);
  const [userId, setUserId] = React.useState<string | null>(null);
  const [authReady, setAuthReady] = React.useState<boolean>(false);
  const [isDev, setIsDev] = React.useState<boolean>(false);
  const isLoggingOut = useRef(false);

  // Recover the chat list from Postgres when localStorage is empty (fresh
  // browser, new device, or cleared storage). Message content always lives in
  // Postgres; this rebuilds the list-metadata localStorage holds. Best-effort.
  const hydrateChatList = useCallback(async (newUserId: string | null) => {
    if (typeof window === "undefined" || !newUserId) return;

    const existingChats = window.localStorage.getItem("mirror_chats");
    const parsed = existingChats ? JSON.parse(existingChats) : [];
    if (parsed.length > 0) return;

    try {
      const { data: { session } } = await createClient().auth.getSession();
      if (!session?.access_token) return;

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/conversations`,
        { headers: { Authorization: `Bearer ${session.access_token}` } },
      );
      if (!res.ok) return;

      const summaries: Array<{
        conversation_id: string;
        first_at: string;
        last_at: string;
        first_user_message: string;
        last_response_text: string;
      }> = await res.json();

      const hydrated = summaries.map(s => ({
        id: s.conversation_id,
        type: dict.modes.primary.id,   // unknown at hydration time; default
        title: s.first_user_message.length > 40
          ? s.first_user_message.slice(0, 40) + "..."
          : s.first_user_message,
        preview: s.last_response_text.slice(0, 120),
        date: new Date(s.last_at).toLocaleDateString("en-US", {
          month: "short", day: "numeric", year: "numeric",
        }),
        lastModified: new Date(s.last_at).getTime(),
        pinned: false,
      }));

      window.localStorage.setItem("mirror_chats", JSON.stringify(hydrated));
      window.dispatchEvent(new Event("localDatabaseSwapped"));
    } catch {
      // Hydration is best-effort — silently skip on network failure.
    }
  }, []);

  const handleUserTransition = useCallback(async (newUserId: string | null) => {
    if (typeof window === "undefined") return;

    // No guest data is ever kept. On any auth state change, blow away the
    // localStorage cache; Supabase is the source of truth.
    window.localStorage.setItem("mirror_chats", "[]");
    window.localStorage.setItem("mirror_memories", "[]");
    window.localStorage.setItem("mirror_active_user", newUserId || "guest");
    window.dispatchEvent(new Event("localDatabaseSwapped"));

    // Then hydrate from Supabase for signed-in users.
    await hydrateChatList(newUserId);
  }, [hydrateChatList]);

  // Gracefully handle silent cookie expirations
  const enforceGuestState = useCallback(() => {
    setIsSignedIn(false);
    setAvatar(null);
    setFullName("User");
  }, [setIsSignedIn, setAvatar, setFullName]);

  useEffect(() => {
    const supabase = createClient();

    supabase.auth.getSession().then(({ data: { session } }) => {
      if (isLoggingOut.current) return;
      const newUserId = session?.user?.id ?? null;
      setIsSignedIn(prev => { const next = !!session; return prev === next ? prev : next; });
      setUserId(prev => prev === newUserId ? prev : newUserId);
      if (!session) enforceGuestState();
      setAuthReady(true);   // session resolved — gates may now trust isSignedIn
      handleUserTransition(newUserId);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (isLoggingOut.current) return;
      const newUserId = session?.user?.id ?? null;
      setIsSignedIn(prev => { const next = !!session; return prev === next ? prev : next; });
      setUserId(prev => prev === newUserId ? prev : newUserId);
      if (!session) enforceGuestState();
      setAuthReady(true);
      handleUserTransition(newUserId);
    });

    return () => {
      subscription.unsubscribe();
    };
  }, [setIsSignedIn, handleUserTransition, enforceGuestState]);

  // Tracks which userId we've already fetched a profile for, so we don't
  // re-fetch on every TOKEN_REFRESHED event and clobber active edits.
  const hasLoadedProfile = useRef<string | null>(null);

  useEffect(() => {
    if (!isSignedIn || !userId) {
      hasLoadedProfile.current = null;
      setIsDev(false);
      return;
    }
    if (hasLoadedProfile.current === userId) return;
    hasLoadedProfile.current = userId;

    // Debug-panel gate: server-owned, never trusted from the client.
    apiClient<{ is_dev?: boolean }>(
      `${process.env.NEXT_PUBLIC_API_URL}/api/v1/account/me`,
    )
      .then((flags) => setIsDev(Boolean(flags?.is_dev)))
      .catch(() => setIsDev(false));

    getUserProfile().then((profile) => {
      if (!profile) return;
      setFullName(profile.full_name || "User");
      setAvatar(profile.avatar_url || null);
      if (profile.theme) {
        window.dispatchEvent(new CustomEvent("syncTheme", { detail: profile.theme }));
      }
      setSettings({
        enterToSend: profile.enter_to_send ?? DEFAULT_SETTINGS.enterToSend,
        memoryPaused: profile.memory_paused ?? DEFAULT_SETTINGS.memoryPaused,
        selectedModel: profile.preferred_model ?? DEFAULT_SETTINGS.selectedModel,
        selectedLanguage: profile.preferred_language ?? DEFAULT_SETTINGS.selectedLanguage,
      });
    });
    // Setters intentionally omitted from deps — their identities change every
    // render (useLocalStorage) and would re-fire this effect, clobbering typed input.
  }, [isSignedIn, userId]);

  const clearSession = () => {
    setAvatar(null);
    setIsSignedIn(false);
    setFullName("User");
    setHasCompletedOnboarding(false);

    window.dispatchEvent(new CustomEvent("syncTheme", { detail: "Dark" }));

    if (typeof window !== "undefined") {
      window.localStorage.removeItem("mirror_avatar");
      window.localStorage.removeItem("mirror_fullname");
        window.localStorage.removeItem("mirror_onboarded");
      window.localStorage.removeItem("mirror_theme");
      window.localStorage.removeItem("mirror_settings");
    }
  };

  const performLogOut = async () => {
    isLoggingOut.current = true;
    setIsSignedIn(false);

    handleUserTransition(null);

    setTimeout(async () => {
      clearSession();
      await logOut();
    }, 150);
  };

  return (
    <UserContext.Provider value={{
      avatar, setAvatar,
      isSignedIn, setIsSignedIn,
      authReady,
      userId,
      fullName, setFullName,
      isDev,
      hasCompletedOnboarding, setHasCompletedOnboarding,
      settings, updateLocalSetting,
      isAuthModalOpen, setIsAuthModalOpen,
      clearSession,
      performLogOut,
    }}>
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (!context) throw new Error("useUser must be used within a UserProvider");
  return context;
}
