import { AppDictionary } from "./types";

export const baseDictionary: AppDictionary = {
  modes: {
    primary: { id: "analysis", label: "Analysis", icon: "sparkle" },
    secondary: { id: "synthesis", label: "Synthesis", icon: "zap" }
  },
  home: {
    title: "A structured model of your thoughts.",
    subtitle: "Not a chat log — a knowledge graph of your recurring themes, the angles you take on them, and what connects them. It gets more accurate the more you use it.",
  },
  memory: {
    categories: [
      { id: "biographical", label: "Biographical" },
      { id: "psychology", label: "Psychology & Mindset" },
      { id: "writing", label: "Writing Preferences" },
      { id: "preferences", label: "Personal Preferences" },
      { id: "rules", label: "Preferences & Limits" }
    ]
  },
  settings: {
    advancedModels: "Custom Endpoints",
  },
  chat: {
    dashboardSubtitle: "Resume a past conversation.",
    processingMessage: (modeLabel: string) => `Continuing ${modeLabel} session. Updating semantic profile...`,
    initialMessages: {
      primary: "What's on your mind today — is there something specific you keep coming back to, or are you just curious what this does?",
      secondary: "What's on your mind today — is there something specific you keep coming back to, or are you just curious what this does?",
      onboarding: "What made you open this up today? We can start wherever you like — a person, a feeling, a project, or something you keep circling."
    }
  }
};