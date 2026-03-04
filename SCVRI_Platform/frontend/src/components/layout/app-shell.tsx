"use client";

import Link from "next/link";
import { PropsWithChildren } from "react";
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
  { label: "Reports", href: "/reports", roles: ["admin", "analyst", "viewer"] },
  { label: "Integrations", href: "/integrations", roles: ["admin"] },
  { label: "Admin", href: "/admin", roles: ["admin"] }
];

export function AppShell({ children }: PropsWithChildren) {
  const { role, notifications } = useAppStore();

  return (
    <div className="flex min-h-screen">
      <aside className="w-64 border-r bg-slate-900 p-4 text-white">
        <h1 className="mb-6 text-lg font-semibold">SCVRI</h1>
        <nav className="space-y-1">
          {navItems.filter((item) => item.roles.includes(role)).map((item) => (
            <Link key={item.href} href={item.href} className="block rounded px-3 py-2 text-sm hover:bg-slate-800">{item.label}</Link>
          ))}
        </nav>
      </aside>
      <div className="flex-1">
        <header className="flex items-center justify-between border-b bg-white p-4">
          <div className="w-full max-w-lg"><SearchInput placeholder="Search suppliers, shipments, risk events, alerts, documents" /></div>
          <div className="ml-4 flex items-center gap-4">
            <div className="max-w-xs space-y-1">
              {notifications.map((note) => <div key={note.id} className="flex items-center gap-2 text-xs"><AlertSeverityIndicator severity={note.severity} />{note.title}</div>)}
            </div>
            <button aria-label="User menu" className="rounded-full bg-slate-200 px-3 py-2 text-sm">Analyst</button>
          </div>
        </header>
        <main className="p-4">{children}</main>
      </div>
    </div>
  );
}
