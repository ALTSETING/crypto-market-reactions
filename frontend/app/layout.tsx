import type { Metadata } from "next";
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
        <ThemeToggle />
        {children}
      </body>
    </html>
  );
}
