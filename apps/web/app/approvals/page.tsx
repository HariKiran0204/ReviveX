"use client";

import Link from "next/link";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/EmptyState";
import { useToast } from "@/components/Toast";
import { ConfirmDialog, ErrorBanner, Skeleton, StatusBadge } from "@/components/ui";
import { decideApproval, fetchApprovals } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

export default function ApprovalsPage() {
  const [status, setStatus] = useState("PENDING");
  const query = useApiQuery(`approvals:${status}`, () =>
    fetchApprovals({ status: status || undefined, page: 1, page_size: 50 }),
  );
  const toast = useToast();
  const [target, setTarget] = useState<{ id: string; action: "approve" | "reject" | "cancel" } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  async function confirm() {
    if (!target) {
      return;
    }
    setBusy(true);
    try {
      await decideApproval(target.id, target.action);
      toast("Backend decision recorded");
      setTarget(null);
      query.reload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="Approvals">
      <label className="mb-4 block max-w-xs text-xs text-slate-400">
        Status
        <select
          className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="PENDING">PENDING</option>
          <option value="APPROVED">APPROVED</option>
          <option value="REJECTED">REJECTED</option>
          <option value="">All</option>
        </select>
      </label>
      {query.status === "loading" ? <Skeleton className="h-64" /> : null}
      {query.status === "error" ? (
        <ErrorBanner message={query.error.message} onRetry={query.reload} />
      ) : null}
      {query.status === "success" && query.data.items.length === 0 ? (
        <EmptyState
          title="Approval queue is empty"
          body="No approvals match this filter. High-value simulated actions appear here after the policy engine requires approval."
        />
      ) : null}
      {query.status === "success" && query.data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-2xl border border-white/10">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-ink-800 text-xs uppercase text-slate-400">
              <tr>
                {[
                  "Case",
                  "Customer",
                  "Amount",
                  "Action",
                  "Reason",
                  "Expected",
                  "Risk",
                  "Expiry",
                  "Status",
                  "",
                ].map((header) => (
                  <th key={header} className="px-4 py-3">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((row) => (
                <tr key={row.id} className="border-t border-white/5">
                  <td className="px-4 py-3">
                    <Link href={`/cases/${row.case_id}`} className="text-accent-400 hover:underline">
                      {row.case_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{row.customer?.full_name || "—"}</td>
                  <td className="px-4 py-3">
                    {formatMoney(row.amount, row.case?.currency || "INR")}
                  </td>
                  <td className="px-4 py-3">{row.proposed_action || "—"}</td>
                  <td className="max-w-xs truncate px-4 py-3 text-slate-400">
                    {row.reason || "—"}
                  </td>
                  <td className="px-4 py-3">{row.expected_value || "—"}</td>
                  <td className="px-4 py-3">{row.risk || "—"}</td>
                  <td className="px-4 py-3">{formatDateTime(row.expires_at)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge value={row.status} />
                  </td>
                  <td className="px-4 py-3">
                    {row.status === "PENDING" ? (
                      <div className="flex gap-1">
                        <button type="button" onClick={() => setTarget({ id: row.id, action: "approve" })}>
                          Approve
                        </button>
                        <button type="button" onClick={() => setTarget({ id: row.id, action: "reject" })}>
                          Reject
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <ConfirmDialog
        open={target !== null}
        title="Confirm operator decision"
        body="This calls the backend ApprovalService. The queue refreshes only after confirmation."
        confirmLabel="Submit"
        busy={busy}
        onCancel={() => setTarget(null)}
        onConfirm={() => void confirm()}
      />
    </AppShell>
  );
}
