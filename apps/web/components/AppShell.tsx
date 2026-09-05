import type { ReactNode } from "react";
import { Header } from "@/components/Header";
import { Sidebar } from "@/components/Sidebar";
import { ToastProvider } from "@/components/Toast";

export function AppShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <ToastProvider>
      <div className="flex min-h-screen bg-ink-900 text-slate-100">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header title={title} />
          <main className="flex-1 px-4 py-6 sm:px-8 sm:py-8">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
