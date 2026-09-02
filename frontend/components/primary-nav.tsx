"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Home" },
  { href: "/events", label: "Events" },
  { href: "/ai", label: "AI Research" },
] as const;

export function PrimaryNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="fixed left-3 top-[max(0.75rem,env(safe-area-inset-top))] z-50 flex max-w-[calc(100vw-4.75rem)] rounded-full border border-[var(--border)] bg-[var(--surface-strong)]/90 p-1 text-[13px] shadow-lg shadow-slate-950/10 backdrop-blur-xl sm:left-5 sm:top-[max(1.25rem,env(safe-area-inset-top))] sm:text-sm"
    >
      {links.map(({ href, label }) => {
        const active = href === "/" ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`min-h-11 rounded-full px-3 py-2.5 font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-emerald-400 sm:px-4 ${active ? "bg-emerald-400/12 text-emerald-300" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}
            href={href}
            key={href}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
