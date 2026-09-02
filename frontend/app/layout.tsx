import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";

import { ThemeToggle } from "@/components/theme-toggle";

import {
  HOME_DESCRIPTION,
  HOME_TITLE,
  resolveSiteUrl,
  SITE_NAME,
  siteUrl,
} from "@/lib/seo";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const themeScript = `(function(){try{var t=localStorage.getItem('site-theme');document.documentElement.dataset.theme=t==='dark'?'dark':'light'}catch(e){document.documentElement.dataset.theme='light'}})()`;

export const metadata: Metadata = {
  metadataBase: resolveSiteUrl(),
  title: {
    default: HOME_TITLE,
    template: `%s | ${SITE_NAME}`,
  },
  description: HOME_DESCRIPTION,
  applicationName: SITE_NAME,
  verification: {
    google: "FJwzMXOGWwmKWe4Uf94wksvdHeorOEsoPV1yJ3pMSZY",
  },
  openGraph: {
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
    url: siteUrl("/"),
    type: "website",
    siteName: SITE_NAME,
  },
  twitter: {
    card: "summary",
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html data-theme="light" lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body className={`${geist.variable} ${geistMono.variable}`}>
        <nav aria-label="Primary" className="fixed left-4 top-4 z-50 flex rounded-full border border-white/10 bg-slate-950/85 p-1 text-sm shadow-xl backdrop-blur sm:left-6">
          <Link className="rounded-full px-3 py-2 text-slate-300 hover:bg-white/10 hover:text-white" href="/">Home</Link>
          <Link className="rounded-full px-3 py-2 text-slate-300 hover:bg-white/10 hover:text-white" href="/events">Events</Link>
          <Link className="rounded-full px-3 py-2 text-slate-300 hover:bg-white/10 hover:text-white" href="/ai">AI Research</Link>
        </nav>
        <ThemeToggle />
        {children}
      </body>
    </html>
  );
}
