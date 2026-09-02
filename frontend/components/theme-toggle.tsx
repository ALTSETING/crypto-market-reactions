"use client";

import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

function subscribeTheme(onStoreChange: () => void): () => void {
  window.addEventListener("site-theme-change", onStoreChange);
  window.addEventListener("storage", onStoreChange);
  return () => {
    window.removeEventListener("site-theme-change", onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => "light");

  function toggleTheme() {
    const next: Theme = theme === "light" ? "dark" : "light";
    window.localStorage.setItem("site-theme", next);
    applyTheme(next);
    window.dispatchEvent(new Event("site-theme-change"));
  }

  const dark = theme === "dark";
  return (
    <button
      aria-label={`Switch to ${dark ? "light" : "dark"} theme`}
      aria-pressed={dark}
      className="fixed right-3 top-[max(0.6rem,env(safe-area-inset-top))] z-50 inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--surface-strong)]/90 px-3 text-xs font-medium text-[var(--text-medium)] shadow-md shadow-slate-950/10 outline-none backdrop-blur-xl transition hover:border-emerald-500/35 hover:text-[var(--text-strong)] focus-visible:ring-2 focus-visible:ring-emerald-400 sm:right-5 sm:top-[max(1rem,env(safe-area-inset-top))]"
      onClick={toggleTheme}
      type="button"
    >
      <span aria-hidden="true" className="text-base">{dark ? "☾" : "☀"}</span>
      <span className="hidden sm:inline">{dark ? "Dark" : "Light"}</span>
    </button>
  );
}
