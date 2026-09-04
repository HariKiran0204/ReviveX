"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner, Skeleton, StatusBadge } from "@/components/ui";
import { fetchCases } from "@/lib/api";
import { formatDateTime, formatMoney, formatPercent } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

export default function CasesPage() {
  const [status, setStatus] = useState("");
  const [caseType, setCaseType] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [sort, setSort] = useState("created_at");
  const [direction, setDirection] = useState("desc");
  const [page, setPage] = useState(1);
  const key = useMemo(
    () => `${status}|${caseType}|${minAmount}|${maxAmount}|${sort}|${direction}|${page}`,
    [status, caseType, minAmount, maxAmount, sort, direction, page],
  );
  const query = useApiQuery(key, () =>
    fetchCases({
      page,
      page_size: 25,
      status: status || undefined,
      case_type: caseType || undefined,
      min_amount: minAmount || undefined,
      max_amount: maxAmount || undefined,
      sort,
      direction,
    }),
  );

  return (
    <AppShell title="Recovery Cases">
      <div className="mb-6 grid gap-3 md:grid-cols-6">
        <label className="text-xs text-slate-400">
          Status
          <select
            className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
            value={status}
            onChange={(event) => {
              setPage(1);
              setStatus(event.target.value);
            }}
          >
            <option value="">All</option>
            {[
              "DETECTED",
              "POLICY_CHECK",
              "AWAITING_APPROVAL",
              "RECOVERED",
              "NOT_RECOVERED",
              "STOPPED",
            ].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Case type
          <select
            className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
            value={caseType}
            onChange={(event) => {
              setPage(1);
              setCaseType(event.target.value);
            }}
          >
            <option value="">All</option>
            <option value="FAILED_PAYMENT">FAILED_PAYMENT</option>
            <option value="ABANDONED_CHECKOUT">ABANDONED_CHECKOUT</option>
            <option value="SUBSCRIPTION_FAILURE">SUBSCRIPTION_FAILURE</option>
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Min amount
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
            value={minAmount}
            onChange={(event) => {
              setPage(1);
              setMinAmount(event.target.value);
            }}
          />
        </label>
        <label className="text-xs text-slate-400">
          Max amount
          <input
            className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
            value={maxAmount}
            onChange={(event) => {
              setPage(1);
              setMaxAmount(event.target.value);
            }}
          />
        </label>
        <label className="text-xs text-slate-400">
          Sort
          <select
            className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="created_at">Created</option>
            <option value="amount_at_risk">Amount at risk</option>
            <option value="amount_recovered">Recovered</option>
            <option value="status">Status</option>
          </select>
        </label>
        <label className="text-xs text-slate-400">
          Direction
          <select
            className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-2 py-2 text-sm text-white"
            value={direction}
            onChange={(event) => setDirection(event.target.value)}
          >
            <option value="desc">Desc</option>
            <option value="asc">Asc</option>
          </select>
        </label>
      </div>
      {query.status === "loading" ? <Skeleton className="h-64" /> : null}
      {query.status === "error" ? (
        <ErrorBanner message={query.error.message} onRetry={query.reload} />
      ) : null}
      {query.status === "success" && query.data.items.length === 0 ? (
        <EmptyState
          title="No recovery cases"
          body="The API returned an empty page for the current filters. Run a demo from Command Center to create a real case."
        />
      ) : null}
      {query.status === "success" && query.data.items.length > 0 ? (
        <>
          <div className="overflow-x-auto rounded-2xl border border-white/10">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-ink-800 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  {[
                    "Customer",
                    "At risk",
                    "Recovered",
                    "Type",
                    "Failure",
                    "State",
                    "P(recovery)",
                    "Action",
                    "ERV",
                    "Created",
                  ].map((header) => (
                    <th key={header} className="px-4 py-3 font-medium">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((row) => (
                  <tr key={row.id} className="border-t border-white/5 hover:bg-white/5">
                    <td className="px-4 py-3">
                      <Link href={`/cases/${row.id}`} className="text-accent-400 hover:underline">
                        {row.customer.full_name || row.customer.email || row.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{formatMoney(row.amount_at_risk, row.currency)}</td>
                    <td className="px-4 py-3">{formatMoney(row.amount_recovered, row.currency)}</td>
                    <td className="px-4 py-3">{row.case_type}</td>
                    <td className="px-4 py-3 text-slate-400">{row.failure_reason || "—"}</td>
                    <td className="px-4 py-3">
                      <StatusBadge value={row.status} />
                    </td>
                    <td className="px-4 py-3">{formatPercent(row.recovery_probability)}</td>
                    <td className="px-4 py-3">{row.recommended_action || "—"}</td>
                    <td className="px-4 py-3">{formatMoney(row.expected_recovery, row.currency)}</td>
                    <td className="px-4 py-3 text-slate-400">{formatDateTime(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
            <span>
              Page {query.data.page} · {query.data.total} total
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded border border-white/15 px-3 py-1 disabled:opacity-40"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="rounded border border-white/15 px-3 py-1 disabled:opacity-40"
                disabled={page * query.data.page_size >= query.data.total}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : null}
    </AppShell>
  );
}
