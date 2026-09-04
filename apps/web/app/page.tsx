"use client";

import Link from "next/link";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ErrorBanner, Skeleton } from "@/components/ui";
import { fetchCommandCenter, runDemo } from "@/lib/api";
import { formatMoney, formatPercent } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

const DEMO_ACTIONS = [
  { kind: "run_demo", label: "Run Demo" },
  { kind: "failed_payment", label: "Create Failed Payment Scenario" },
  { kind: "approval", label: "Create Approval Scenario" },
  { kind: "policy_block", label: "Create Policy Block Scenario" },
  { kind: "verification_mismatch", label: "Create Verification Mismatch Scenario" },
] as const;

export default function CommandCenterPage() {
  const query = useApiQuery("command-center", fetchCommandCenter, { refreshMs: 20_000 });
  const toast = useToast();
  const [demoBusy, setDemoBusy] = useState<string | null>(null);
  const [demoResult, setDemoResult] = useState<string | null>(null);

  async function onDemo(kind: string) {
    setDemoBusy(kind);
    try {
      const result = await runDemo(kind);
      const ids = result.cases.map((item) => item.id.slice(0, 8)).join(", ") || "none yet";
      setDemoResult(`${result.kind}: ${result.cases.length} case(s) ${ids}`);
      toast("Demo scenario executed on the backend");
      query.reload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Demo failed", "error");
    } finally {
      setDemoBusy(null);
    }
  }

  return (
    <AppShell title="Command Center">
      <p className="max-w-3xl text-sm leading-6 text-slate-400">
        Metrics are read from PostgreSQL through the RecoverAI API. Expected recovery is an ERV
        estimate. Actual recovered revenue is only the amount credited after verification.
      </p>
      {query.status === "loading" ? (
        <div className="mt-8 grid gap-4 md:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-28" />
          ))}
        </div>
      ) : null}
      {query.status === "error" ? (
        <div className="mt-8">
          <ErrorBanner message={query.error.message} onRetry={query.reload} />
        </div>
      ) : null}
      {query.status === "success" ? (
        <>
          {query.data.partial ? (
            <p className="mt-6 text-sm text-amber-200">
              Partial data: no merchant records yet. Figures below are zeros, not estimates.
            </p>
          ) : null}
          <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Revenue at risk"
              value={formatMoney(query.data.revenue_at_risk, query.data.currency)}
              hint="ACTUAL remaining exposure on open cases"
            />
            <Metric
              label="Revenue recovered"
              value={formatMoney(query.data.revenue_recovered, query.data.currency)}
              hint="ACTUAL verified recovery"
            />
            <Metric
              label="Expected recovery"
              value={formatMoney(query.data.expected_recovery, query.data.currency)}
              hint="EXPECTED from latest ERV decisions"
            />
            <Metric
              label="Recovery rate"
              value={formatPercent(query.data.recovery_rate)}
              hint="Recovered ÷ closed cases"
            />
            <Metric label="Active cases" value={String(query.data.active_cases)} />
            <Metric label="Pending approvals" value={String(query.data.pending_approvals)} />
            <Metric label="Failed actions" value={String(query.data.failed_actions)} />
            <Metric label="Policy blocks" value={String(query.data.policy_blocks)} />
          </div>
        </>
      ) : null}

      <section className="mt-12">
        <h2 className="font-display text-xl text-white">Live demo controls</h2>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          These buttons call <code className="text-accent-400">POST /v1/operator/demo</code> and
          run the existing simulator plus recovery pipeline. They do not invent frontend-only cases.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {DEMO_ACTIONS.map((item) => (
            <button
              key={item.kind}
              type="button"
              disabled={demoBusy !== null}
              onClick={() => void onDemo(item.kind)}
              className="rounded-lg border border-white/15 bg-ink-800 px-3 py-2 text-sm hover:bg-white/5 disabled:opacity-50"
            >
              {demoBusy === item.kind ? "Running…" : item.label}
            </button>
          ))}
        </div>
        {demoResult ? (
          <p className="mt-3 text-sm text-slate-300">
            Last result: {demoResult}.{" "}
            <Link href="/cases" className="text-accent-400 underline">
              Open cases
            </Link>
          </p>
        ) : null}
      </section>
    </AppShell>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <article className="rounded-2xl border border-white/10 bg-ink-800/70 p-5">
      <h3 className="text-xs uppercase tracking-wide text-slate-400">{label}</h3>
      <p className="mt-2 font-display text-2xl text-white">{value}</p>
      {hint ? <p className="mt-2 text-xs text-slate-500">{hint}</p> : null}
    </article>
  );
}
