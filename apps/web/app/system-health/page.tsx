"use client";

import { AppShell } from "@/components/AppShell";
import { ErrorBanner, Skeleton, StatusBadge } from "@/components/ui";
import { fetchSystemHealth } from "@/lib/api";
import { useApiQuery } from "@/lib/useApiQuery";

export default function SystemHealthPage() {
  const query = useApiQuery("system-health", fetchSystemHealth, { refreshMs: 15_000 });

  return (
    <AppShell title="System Health">
      <p className="mb-6 max-w-2xl text-sm text-slate-400">
        Live checks from the API. Provider and LLM statuses are not fabricated: the stub LLM is
        reported unavailable, and Razorpay is unavailable until Phase 10.
      </p>
      {query.status === "loading" ? <Skeleton className="h-40" /> : null}
      {query.status === "error" ? (
        <ErrorBanner message={query.error.message} onRetry={query.reload} />
      ) : null}
      {query.status === "success" ? (
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {query.data.checks.map((item) => (
            <div key={item.name} className="rounded-xl border border-white/10 bg-ink-800/80 p-4">
              <dt className="flex items-center justify-between text-xs uppercase tracking-wide text-slate-400">
                {item.name}
                <StatusBadge value={item.status} />
              </dt>
              <dd className="mt-2 text-sm text-slate-200">{item.detail}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </AppShell>
  );
}
