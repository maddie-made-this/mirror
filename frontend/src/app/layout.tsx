import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers"; 
import "./globals.css";
import AppLayout from "@/components/layout/AppLayout"; 
import { GlobalProviders } from "@/context/Providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Mirror AI",
  description: "A structured model of your thoughts — a knowledge graph of your recurring themes, built from your own conversations.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  const sidebarCookie = cookieStore.get("sidebarCollapsed");
  const defaultCollapsed = sidebarCookie?.value === "true";

  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-[var(--background)] text-[var(--foreground)] transition-colors duration-500">
        <GlobalProviders>
          <AppLayout defaultCollapsed={defaultCollapsed}>
            {children}
          </AppLayout>
        </GlobalProviders>
      </body>
    </html>
  );
}