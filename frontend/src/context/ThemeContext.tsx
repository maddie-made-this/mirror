"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { ThemeModal } from "@/components/features/settings/SettingsModals";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { updateSettings } from "@/app/actions/auth";

interface ThemeContextType {
  selectedTheme: string;
  setTheme: (theme: string) => void;
  openThemeModal: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedTheme, setSelectedTheme, isLoaded] = useLocalStorage("mirror_theme", "Dark");

  const applyThemeToDOM = useCallback((themeName: string) => {
    if (themeName === "Follow System Settings") {
      const isSystemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.setAttribute("data-theme", isSystemDark ? "Dark" : "Light");
    } else {
      document.documentElement.setAttribute("data-theme", themeName);
    }
  }, []);

  useEffect(() => {
    if (isLoaded) applyThemeToDOM(selectedTheme);
  }, [selectedTheme, isLoaded, applyThemeToDOM]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleSystemThemeChange = (e: MediaQueryListEvent) => {
      if (selectedTheme === "Follow System Settings") {
        document.documentElement.setAttribute("data-theme", e.matches ? "Dark" : "Light");
      }
    };
    mediaQuery.addEventListener("change", handleSystemThemeChange);
    return () => mediaQuery.removeEventListener("change", handleSystemThemeChange);
  }, [selectedTheme]);

  // Listen for DB sync events emitted by UserContext upon login/logout
  useEffect(() => {
    const handleSync = (e: any) => {
      if (e.detail) setSelectedTheme(e.detail);
    };
    window.addEventListener('syncTheme', handleSync);
    return () => window.removeEventListener('syncTheme', handleSync);
  }, [setSelectedTheme]);

  // Automatically push to DB when user makes a change in Settings
  const handleThemeChange = async (newTheme: string) => {
    setSelectedTheme(newTheme);
    await updateSettings({ theme: selectedTheme }); 
  };

  const standardThemes = ["Follow System Settings", "Light", "Dark", "High Contrast", "Colorblind Safe (Protanopia)", "Colorblind Safe (Deuteranopia)"];
  const colorGrid = [
    ["Salmon", "Peach", "Butter", "Mint", "Sky", "Periwinkle", "Lavender", "Silver"],
    ["Crimson", "Tangerine", "Mustard", "Emerald", "Cobalt", "Sapphire", "Plum", "Slate"],
    ["Ruby", "Neon Orange", "Cyber Yellow", "Lime", "Cyan", "Electric Blue", "Fuchsia", "Charcoal"]
  ];

  return (
    <ThemeContext.Provider value={{ selectedTheme, setTheme: handleThemeChange, openThemeModal: () => setIsModalOpen(true) }}>
      {children}
      {isModalOpen && (
        <ThemeModal 
          selectedTheme={selectedTheme} 
          onSelect={handleThemeChange} 
          onClose={() => setIsModalOpen(false)}
          standardThemes={standardThemes}
          colorGrid={colorGrid}
        />
      )}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within a ThemeProvider");
  return context;
}