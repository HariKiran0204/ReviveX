"use client";

import { useEffect, useState } from "react";
import { fetchHealth, fetchReady } from "@/lib/api";
import type { HealthSnapshot } from "@/lib/types";

function labelFor(snapshot: HealthSnapshot): string {
  if (snapshot.state === "loading") {
    return "Checking…";
  }
  if (snapshot.state === "healthy") {
    return "API: Healthy";
  }
  if (snapshot.state === "unhealthy") {
    return "API: Degraded";
  }
  return "API: Unavailable";
}

export function HealthStatus() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [health, ready] = await Promise.all([fetchHealth(), fetchReady()]);
        if (cancelled) {
          return;
        }
        const healthy = health.status === "ok" && ready.status === "ready";
        setSnapshot({
          state: healthy ? "healthy" : "unhealthy",
          health,
          ready,
          message: healthy ? "All configured checks passed." : "One or more checks failed.",
        });
      } catch {
        if (!cancelled) {
          setSnapshot({
            state: "error",
            health: null,
            ready: null,
            message: "Could not reach the RecoverAI API.",
          });
        }
      }
    }

    void load();
    if (process.env.NODE_ENV === "test") {
      return () => {
        cancelled = true;
      };
    }
    const timer = window.setInterval(() => {
      void load();
    }, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const tone =
    snapshot.state === "healthy"
      ? "bg-accent-500"
      : snapshot.state === "loading"
        ? "bg-slate-400"
        : "bg-rose-500";

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-200"
      data-testid="health-status"
      title={snapshot.state === "loading" ? "Checking backend" : snapshot.message}
    >
      <span className={`h-2 w-2 rounded-full ${tone}`} aria-hidden="true" />
      <span>{labelFor(snapshot)}</span>
    </div>
  );
}

export function ReadyChecksPanel() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [health, ready] = await Promise.all([fetchHealth(), fetchReady()]);
        if (!cancelled) {
          setSnapshot({
            state: health.status === "ok" && ready.status === "ready" ? "healthy" : "unhealthy",
            health,
            ready,
            message: "",
          });
        }
      } catch {
        if (!cancelled) {
          setSnapshot({
            state: "error",
            health: null,
            ready: null,
            message: "Could not reach the RecoverAI API.",
          });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (snapshot.state === "loading") {
    return <p className="text-sm text-slate-400">Loading live dependency checks…</p>;
  }
  if (snapshot.state === "error" || !snapshot.ready) {
    return (
      <p className="text-sm text-rose-300">
        Backend unreachable. Start the API, then refresh this page.
      </p>
    );
  }

  const entries = Object.entries(snapshot.ready.checks);
  return (
    <dl className="grid gap-3 sm:grid-cols-3">
      {entries.map(([name, status]) => (
        <div key={name} className="rounded-xl border border-white/10 bg-ink-800/80 p-4">
          <dt className="text-xs uppercase tracking-wide text-slate-400">{name}</dt>
          <dd className="mt-1 font-medium capitalize text-slate-100">{status}</dd>
        </div>
      ))}
    </dl>
  );
}
