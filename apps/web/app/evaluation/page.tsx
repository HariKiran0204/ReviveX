"use client";

import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner, Skeleton } from "@/components/ui";
import { fetchEvaluation } from "@/lib/api";
import { useApiQuery } from "@/lib/useApiQuery";

export default function EvaluationPage() {
  const query = useApiQuery("evaluation", fetchEvaluation);

  return (
    <AppShell title="Evaluation Center">
      {query.status === "loading" ? <Skeleton className="h-64" /> : null}
      {query.status === "error" ? (
        <ErrorBanner message={query.error.message} onRetry={query.reload} />
      ) : null}
      {query.status === "success" && !query.data.available ? (
        <EmptyState
          title="No evaluation artifacts"
          body="Train the recovery model to persist held-out metrics. This page will not invent production Razorpay results."
        />
      ) : null}
      {query.status === "success" && query.data.available ? (
        <div className="space-y-8">
          {/* Header Notice Banner */}
          <div className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3.5 text-sm text-emerald-100">
            <span className="font-semibold text-emerald-300">Simulation / Evaluation Results:</span>{" "}
            Held-out paired counterfactual simulation comparing passive Baseline (DO_NOTHING) vs ReviveX ML Strategy. Not production Razorpay results.
          </div>

          {/* Primary Batch Evaluation Highlights */}
          {query.data.baseline_vs_optimizer ? (
            <div className="space-y-4">
              <h2 className="text-base font-semibold tracking-wide text-white">
                ReviveX ML vs Passive Baseline Performance
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <HighlightStat
                  label="Revenue at Risk"
                  value={`₹${query.data.baseline_vs_optimizer.revenue_at_risk}`}
                  subtext={`${query.data.baseline_vs_optimizer.n_cases} cases (Seed ${query.data.baseline_vs_optimizer.seed})`}
                />
                <HighlightStat
                  label="Baseline Recovered"
                  value={`₹${query.data.baseline_vs_optimizer.baseline_recovered}`}
                  subtext={`${query.data.baseline_vs_optimizer.baseline_cases_recovered} cases (${query.data.baseline_vs_optimizer.baseline_recovery_rate}%)`}
                />
                <HighlightStat
                  label="ReviveX ML Recovered"
                  value={`₹${query.data.baseline_vs_optimizer.revivex_recovered}`}
                  subtext={`${query.data.baseline_vs_optimizer.revivex_cases_recovered} cases (${query.data.baseline_vs_optimizer.revivex_recovery_rate}%)`}
                  highlight
                />
                <HighlightStat
                  label="Incremental Revenue"
                  value={`+₹${query.data.baseline_vs_optimizer.incremental_revenue}`}
                  subtext="Net value added"
                  highlight
                />
                <HighlightStat
                  label="Recovery Uplift"
                  value={`+${query.data.baseline_vs_optimizer.recovery_uplift_percent}%`}
                  subtext="Gross recovery boost"
                  highlight
                />
              </div>

              {/* Secondary Metrics & Execution Details */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Stat
                  label="ReviveX Net Recovery"
                  value={`₹${query.data.baseline_vs_optimizer.revivex_net_recovery}`}
                />
                <Stat
                  label="Baseline Net Recovery"
                  value={`₹${query.data.baseline_vs_optimizer.baseline_net_recovery}`}
                />
                <Stat
                  label="ReviveX Mode"
                  value={query.data.baseline_vs_optimizer.revivex_mode.toUpperCase()}
                />
                <Stat
                  label="ML Predictions / Fallbacks"
                  value={`${query.data.baseline_vs_optimizer.ml_prediction_count} ML / ${query.data.baseline_vs_optimizer.heuristic_fallback_count} Fallbacks`}
                />
              </div>

              {/* Multi-Seed Robustness View */}
              {query.data.baseline_vs_optimizer.multi_seed_results &&
              query.data.baseline_vs_optimizer.multi_seed_results.length > 0 ? (
                <div className="space-y-3 pt-2">
                  <h3 className="text-sm font-semibold text-slate-200">
                    Multi-Seed Counterfactual Robustness (Seeds 42–46)
                  </h3>
                  <div className="overflow-x-auto rounded-xl border border-white/10 bg-ink-800/80">
                    <table className="w-full text-left text-xs text-slate-300">
                      <thead className="border-b border-white/10 bg-white/5 uppercase tracking-wider text-slate-400">
                        <tr>
                          <th className="px-4 py-3">Seed</th>
                          <th className="px-4 py-3">Revenue at Risk</th>
                          <th className="px-4 py-3">Baseline Recovered</th>
                          <th className="px-4 py-3">ReviveX ML Recovered</th>
                          <th className="px-4 py-3">Incremental Revenue</th>
                          <th className="px-4 py-3">Gross Uplift</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {query.data.baseline_vs_optimizer.multi_seed_results.map((row) => (
                          <tr key={row.seed} className="hover:bg-white/5">
                            <td className="px-4 py-2.5 font-mono text-emerald-400">Seed {row.seed}</td>
                            <td className="px-4 py-2.5">₹{row.revenue_at_risk}</td>
                            <td className="px-4 py-2.5 text-slate-400">
                              ₹{row.baseline_recovered} ({row.baseline_cases_recovered} cases)
                            </td>
                            <td className="px-4 py-2.5 font-medium text-emerald-300">
                              ₹{row.revivex_recovered} ({row.revivex_cases_recovered} cases)
                            </td>
                            <td className="px-4 py-2.5 font-medium text-emerald-400">
                              +₹{row.incremental_revenue}
                            </td>
                            <td className="px-4 py-2.5 font-semibold text-emerald-300">
                              +{row.recovery_uplift_percent}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Model Artifact Information */}
          <div className="space-y-4 pt-2">
            <h2 className="text-base font-semibold tracking-wide text-white">
              Trained Model Artifact Details ({query.data.model_version || "recovery-v1"})
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Model Version" value={query.data.model_version || "recovery-v1"} />
              <Stat label="Dataset Version" value={query.data.dataset_version || "—"} />
              <Stat label="ROC-AUC" value={fmt(query.data.roc_auc)} />
              <Stat label="PR-AUC" value={fmt(query.data.pr_auc)} />
              <Stat label="Brier Score" value={fmt(query.data.brier)} />
              <Stat label="ECE" value={fmt(query.data.ece)} />
              <Stat label="Algorithm" value={query.data.algorithm || "—"} />
              <Stat
                label="Quality Gate"
                value={query.data.quality_passed == null ? "—" : query.data.quality_passed ? "PASSED" : "FAILED"}
              />
            </div>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}

function HighlightStat({
  label,
  value,
  subtext,
  highlight = false,
}: {
  label: string;
  value: string;
  subtext?: string;
  highlight?: boolean;
}) {
  return (
    <article
      className={`rounded-2xl border p-4 transition-colors ${
        highlight
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
          : "border-white/10 bg-ink-800/70 text-white"
      }`}
    >
      <h3 className="text-xs uppercase tracking-wide text-slate-400">{label}</h3>
      <p className={`mt-2 text-lg font-bold break-all ${highlight ? "text-emerald-300" : "text-white"}`}>
        {value}
      </p>
      {subtext ? <p className="mt-1 text-xs text-slate-400">{subtext}</p> : null}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded-2xl border border-white/10 bg-ink-800/70 p-4">
      <h3 className="text-xs uppercase tracking-wide text-slate-400">{label}</h3>
      <p className="mt-2 break-all text-sm font-semibold text-white">{value}</p>
    </article>
  );
}

function fmt(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return value.toFixed(4);
}
