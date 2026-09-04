"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS } from "@/lib/nav";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-white/10 bg-ink-950/90">
      <div className="border-b border-white/10 px-6 py-6">
        <Link href="/" className="block">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-500 font-display text-sm font-semibold text-ink-950">
              R
            </span>
            <div>
              <p className="font-display text-base tracking-tight text-white">RecoverAI</p>
              <p className="text-[11px] uppercase tracking-[0.16em] text-slate-400">
                Revenue recovery
              </p>
            </div>
          </div>
        </Link>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/" && (pathname ?? "").startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`block rounded-lg px-3 py-2 text-sm transition ${
                active
                  ? "bg-white/10 text-white"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <p className="px-6 py-4 text-[11px] text-slate-500">Phase 9 · Operator UI</p>
    </aside>
  );
}
