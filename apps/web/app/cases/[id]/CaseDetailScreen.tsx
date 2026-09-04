"use client";

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ConfirmDialog, ErrorBanner, Skeleton, StatusBadge } from "@/components/ui";
import {
  decideApproval,
  fetchAgentRuns,
  fetchCase,
  fetchCaseDecision,
  fetchCaseTimeline,
  fetchToolCalls,
} from "@/lib/api";
import { formatDateTime, formatMoney, formatPercent } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

export function CaseDetailScreen({ caseId }: { caseId: string }) {
  const id = caseId;
  const toast = useToast();
  const detail = useApiQuery(`case:${id}`, () => fetchCase(id));
  const decision = useApiQuery(`decision:${id}`, () => fetchCaseDecision(id));
  const timeline = useApiQuery(`timeline:${id}`, () => fetchCaseTimeline(id), {
    refreshMs: 8000,
  });
  const runs = useApiQuery(`runs:${id}`, () => fetchAgentRuns(id));
  const tools = useApiQuery(`tools:${id}`, () => fetchToolCalls(id));
  const [pending, setPending] = useState<"approve" | "reject" | "cancel" | null>(null);
  const [busy, setBusy] = useState(false);

  const approval = detail.status === "success" ? detail.data.approval : null;

  async function confirmDecision() {
    if (!approval || !pending) {
      return;
    }
    setBusy(true);
    try {
      await decideApproval(approval.id, pending);
      toast("Decision submitted; refreshing case from backend");
      setPending(null);
      detail.reload();
      decision.reload();
      timeline.reload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Decision failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="Case Detail">
      {detail.status === "loading" ? <Skeleton className="h-96" /> : null}
      {detail.status === "error" ? (
        <ErrorBanner message={detail.error.message} onRetry={detail.reload} />
      ) : null}
      {detail.status === "success" ? (
        <div className="space-y-8">
          <section className="grid gap-4 lg:grid-cols-3">
            <article className="rounded-2xl border border-white/10 bg-ink-800/70 p-5">
              <h2 className="text-xs uppercase tracking-wide text-slate-400">Customer</h2>
              <p className="mt-2 text-lg text-white">
                {detail.data.customer.full_name || "Unknown customer"}
              </p>
              <p className="text-sm text-slate-400">{detail.data.customer.email || "—"}</p>
            </article>
            <article className="rounded-2xl border border-white/10 bg-ink-800/70 p-5">
              <h2 className="text-xs uppercase tracking-wide text-slate-400">Amounts</h2>
              <p className="mt-2 text-sm text-slate-300">
                At risk: {formatMoney(detail.data.case.amount_at_risk, detail.data.case.currency)}
              </p>
              <p className="text-sm text-slate-300">
                Actual recovered:{" "}
                {formatMoney(detail.data.case.amount_recovered, detail.data.case.currency)}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                Actual recovered is verification-only. This page cannot write amount_recovered.
              </p>
            </article>
            <article className="rounded-2xl border border-white/10 bg-ink-800/70 p-5">
              <h2 className="text-xs uppercase tracking-wide text-slate-400">State</h2>
              <div className="mt-2">
                <StatusBadge value={detail.data.case.status} />
              </div>
              <p className="mt-2 text-sm text-slate-400">
                P(recovery) {formatPercent(detail.data.case.recovery_probability)}
              </p>
            </article>
          </section>

          <section className="rounded-2xl border border-white/10 p-5">
            <h2 className="font-display text-lg text-white">Payment</h2>
            {detail.data.payment ? (
              <dl className="mt-3 grid gap-3 sm:grid-cols-3 text-sm">
                <div>
                  <dt className="text-slate-500">Status</dt>
                  <dd>{detail.data.payment.status}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Amount</dt>
                  <dd>{formatMoney(detail.data.payment.amount, detail.data.payment.currency)}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Failure</dt>
                  <dd>{detail.data.payment.failure_reason || "—"}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-2 text-sm text-slate-400">No payment linked.</p>
            )}
            <p className="mt-3 text-xs text-slate-500">
              Verification mismatch: {detail.data.verification.last_mismatch_reason || "none"}
            </p>
          </section>

          {approval && approval.status === "PENDING" ? (
            <section className="rounded-2xl border border-amber-400/30 bg-amber-400/5 p-5">
              <h2 className="font-display text-lg text-white">Approval required</h2>
              <p className="mt-2 text-sm text-slate-300">
                Proposed {detail.data.selected_action || "action"} · expected{" "}
                {formatMoney(detail.data.case.expected_recovery, detail.data.case.currency)} ·
                expires {formatDateTime(approval.expires_at)}
              </p>
              <p className="mt-1 text-sm text-slate-400">{detail.data.policy_verdict}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-lg bg-accent-500 px-3 py-2 text-sm text-ink-950"
                  onClick={() => setPending("approve")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-white/15 px-3 py-2 text-sm"
                  onClick={() => setPending("reject")}
                >
                  Reject
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-white/15 px-3 py-2 text-sm"
                  onClick={() => setPending("cancel")}
                >
                  Cancel
                </button>
              </div>
            </section>
          ) : null}

          <section className="rounded-2xl border border-white/10 p-5">
            <h2 className="font-display text-lg text-white">AI decision</h2>
            {decision.status === "loading" ? <Skeleton className="mt-3 h-24" /> : null}
            {decision.status === "error" ? (
              <p className="mt-2 text-sm text-rose-300">{decision.error.message}</p>
            ) : null}
            {decision.status === "success" ? (
              <div className="mt-3 space-y-3 text-sm">
                <StatusBadge value={decision.data.source_label} />
                <p>Diagnosis: {decision.data.diagnosis?.root_cause || "No diagnosis stored"}</p>
                <p>Confidence: {formatPercent(decision.data.confidence)}</p>
                <p>Selected action: {decision.data.selected_action || "—"}</p>
                <p>Policy: {decision.data.policy_result || "—"}</p>
                <p>Explanation: {decision.data.explanation || "—"}</p>
                {decision.data.evidence.length > 0 ? (
                  <ul className="list-disc pl-5 text-slate-400">
                    {decision.data.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {decision.data.model_probabilities.length > 0 ? (
                  <table className="mt-2 w-full text-left text-xs">
                    <thead>
                      <tr className="text-slate-500">
                        <th className="py-1">Action</th>
                        <th>P(recovery)</th>
                        <th>ERV</th>
                      </tr>
                    </thead>
                    <tbody>
                      {decision.data.model_probabilities.map((row) => (
                        <tr key={row.action}>
                          <td className="py-1">{row.action}</td>
                          <td>{formatPercent(row.probability)}</td>
                          <td>{decision.data.expected_values[row.action] || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <article className="rounded-2xl border border-white/10 p-5">
              <h2 className="font-display text-lg text-white">Agent runs</h2>
              {runs.status === "success" && runs.data.items.length === 0 ? (
                <p className="mt-2 text-sm text-slate-400">No agent runs for this case.</p>
              ) : null}
              {runs.status === "success"
                ? runs.data.items.map((row) => (
                    <p key={row.id} className="mt-2 text-sm text-slate-300">
                      {row.agent_name} {row.agent_version} · {row.status} · {row.source || "—"}
                    </p>
                  ))
                : null}
            </article>
            <article className="rounded-2xl border border-white/10 p-5">
              <h2 className="font-display text-lg text-white">Tool calls</h2>
              {tools.status === "success" && tools.data.items.length === 0 ? (
                <p className="mt-2 text-sm text-slate-400">No tool calls recorded.</p>
              ) : null}
              {tools.status === "success"
                ? tools.data.items.map((row) => (
                    <p key={row.id} className="mt-2 text-sm text-slate-300">
                      {row.tool_name} · {row.status}
                    </p>
                  ))
                : null}
            </article>
          </section>

          <section className="rounded-2xl border border-white/10 p-5">
            <h2 className="font-display text-lg text-white">Audit / event timeline</h2>
            <p className="mt-1 text-xs text-slate-500">
              Polled from existing audit events every 8 seconds. No second event bus.
            </p>
            {timeline.status === "success" && timeline.data.items.length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">No events yet.</p>
            ) : null}
            <ol className="mt-4 space-y-3">
              {timeline.status === "success"
                ? timeline.data.items.map((item) => (
                    <li key={item.id} className="border-l border-white/15 pl-4 text-sm">
                      <p className="text-slate-500">{formatDateTime(item.timestamp)}</p>
                      <p className="text-white">{item.event_type}</p>
                      <p className="text-slate-400">{item.summary}</p>
                    </li>
                  ))
                : null}
            </ol>
          </section>
        </div>
      ) : null}
      <ConfirmDialog
        open={pending !== null}
        title={`${pending ? pending[0]?.toUpperCase() : ""}${pending?.slice(1)} this action?`}
        body="The backend remains authoritative. The UI will refresh only after the API confirms."
        confirmLabel="Confirm"
        busy={busy}
        onCancel={() => setPending(null)}
        onConfirm={() => void confirmDecision()}
      />
    </AppShell>
  );
}
