export interface AppDictionary {
  modes: {
    primary: { 
      id: string; 
      label: string; 
      icon: "sparkle" | "zap";
    };
    secondary: { 
      id: string; 
      label: string; 
      icon: "sparkle" | "zap";
    };
  };
  home: {
    title: string;
    subtitle: string;
  };
  memory: {
    categories: Array<{ id: string; label: string; }>;
  };
  settings: {
    advancedModels: string;
  };
  chat: {
    dashboardSubtitle: string;
    processingMessage: (modeLabel: string) => string;
    initialMessages: {
      primary: string;
      secondary: string;
      onboarding: string;
    };
  };
}