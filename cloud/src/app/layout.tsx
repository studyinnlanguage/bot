import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Weexionic — Quad-Trend Engine | Cloud Trading App",
  description: "Automated futures trading with military-grade 1:1 risk discipline. Login once — your terminal, positions, keys and history follow your ID.",
  keywords: ["Weexionic", "Trading Bot", "Quad-Trend Engine", "EMA Cross", "Futures", "Cloud Trading"],
  icons: {
    icon: "https://z-cdn.chatglm.cn/z-ai/static/logo.svg",
  },
  openGraph: {
    title: "Weexionic — Quad-Trend Engine",
    description: "Automated futures trading with military-grade 1:1 risk discipline.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
