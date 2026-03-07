"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, PropsWithChildren } from "react";
import { NavItem } from "@/types/navigation";
import { useAppStore } from "@/store/useAppStore";
import { SearchInput } from "@/design-system/components/inputs";
import { AlertSeverityIndicator } from "@/design-system/components/status-badges";

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", roles: ["admin", "analyst", "viewer"] },
  { label: "Supply Chain Map", href: "/supply-chain-map", roles: ["admin", "analyst", "viewer"] },
  { label: "Suppliers", href: "/suppliers", roles: ["admin", "analyst"] },
  { label: "Risk Intelligence", href: "/risk-intelligence", roles: ["admin", "analyst"] },
  { label: "Alerts", href: "/alerts", roles: ["admin", "analyst"] },
  { label: "Shipments", href: "/shipments", roles: ["admin", "analyst"] },
  { label: "Reports", href: "/reports", roles: ["admin", "analyst", "viewer"] },
  { label: "Integrations", href: "/integrations", roles: ["admin"] },
  { label: "Admin", href: "/admin", roles: ["admin"] }
];

function BellIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
      <path d="M10 2a6 6 0 0 0-6 6v2.586l-.707.707A1 1 0 0 0 4 13h12a1 1 0 0 0 .707-1.707L16 10.586V8a6 6 0 0 0-6-6zm0 16a2 2 0 0 0 2-2H8a2 2 0 0 0 2 2z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const { role, notifications, darkMode, toggleDarkMode, clearUser } = useAppStore();
  const pathname = usePathname();
  const router = useRouter();
  const [bellOpen, setBellOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  /* Sync dark class on <html> */
  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
  }, [darkMode]);

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    clearUser();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen bg-page">
      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside className="flex w-56 flex-col bg-sidebar">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 border-b border-white/10 px-5">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-xs font-bold text-white">
            S
          </div>
          <span className="text-sm font-semibold tracking-wide text-brand-powder">SCVRI</span>
        </div>

        {/* Nav links */}
        <nav className="flex-1 space-y-0.5 px-3 py-3">
          {navItems.filter((item) => item.roles.includes(role)).map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center rounded-md px-3 py-2 text-sm transition-colors ${
                pathname === item.href
                  ? "bg-[var(--nav-active-bg)] font-medium text-accent"
                  : "text-[var(--nav-text)] hover:bg-[var(--nav-hover-bg)]"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>

      </aside>

      {/* ── Main column ─────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header className="flex h-14 shrink-0 items-center gap-4 border-b border-stroke bg-topbar px-6">
          <div className="flex-1">
            <SearchInput placeholder="Search suppliers, shipments, alerts…" />
          </div>

          {/* Dark / light toggle */}
          <button
            onClick={toggleDarkMode}
            aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
            title={darkMode ? "Light mode" : "Dark mode"}
            className="flex h-8 w-8 items-center justify-center rounded-full text-ink-3 transition-colors hover:bg-surface"
          >
            {darkMode ? <SunIcon /> : <MoonIcon />}
          </button>

          {/* Bell */}
          <div className="relative">
            <button
              aria-label="Notifications"
              onClick={() => setBellOpen((o) => !o)}
              className="relative rounded-full p-1.5 text-ink-3 transition-colors hover:bg-surface"
            >
              <BellIcon />
              {notifications.length > 0 && (
                <span className="absolute right-0.5 top-0.5 flex h-2 w-2 rounded-full bg-copper" />
              )}
            </button>

            {bellOpen && (
              <div className="absolute right-0 top-10 z-50 w-80 rounded-lg border border-stroke bg-card shadow-xl">
                <p className="border-b border-stroke px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-3">
                  Notifications
                </p>
                {notifications.length === 0 ? (
                  <p className="px-4 py-3 text-sm text-ink-3">All clear</p>
                ) : (
                  <ul>
                    {notifications.map((note) => (
                      <li key={note.id} className="flex items-start gap-3 border-b border-stroke px-4 py-3 last:border-0">
                        <AlertSeverityIndicator severity={note.severity} />
                        <span className="text-sm text-ink-2">{note.title}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* User menu */}
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen((o) => !o)}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-copper text-xs font-semibold uppercase text-white hover:opacity-90"
              aria-label="User menu"
            >
              {role.slice(0, 2)}
            </button>

            {userMenuOpen && (
              <div className="absolute right-0 top-10 z-50 w-44 rounded-lg border border-stroke bg-card shadow-xl">
                <div className="border-b border-stroke px-4 py-2.5">
                  <p className="text-xs font-semibold capitalize text-ink">{role}</p>
                  <p className="text-xs text-ink-3">SCVRI Platform</p>
                </div>
                <button
                  onClick={handleLogout}
                  className="w-full px-4 py-2.5 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
