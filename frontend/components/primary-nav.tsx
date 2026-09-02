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
      className="fixed left-3 top-[max(0.6rem,env(safe-area-inset-top))] z-50 flex max-w-[calc(100vw-4.25rem)] rounded-2xl border border-[var(--border)] bg-[var(--surface-strong)]/90 p-0.5 text-xs shadow-md shadow-slate-950/10 backdrop-blur-xl sm:left-5 sm:top-[max(1rem,env(safe-area-inset-top))] sm:text-[13px]"
    >
      {links.map(({ href, label }) => {
        const active = href === "/" ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`min-h-10 rounded-xl px-2.5 py-2 font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-emerald-400 sm:px-3.5 ${active ? "bg-emerald-400/10 text-emerald-300" : "text-slate-400 hover:text-white"}`}
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
