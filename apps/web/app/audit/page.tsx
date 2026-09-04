"use client";

import { useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner, Skeleton } from "@/components/ui";
import { fetchAudit } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApiQuery } from "@/lib/useApiQuery";

export default function AuditPage() {
  const [caseId, setCaseId] = useState("");
  const [eventType, setEventType] = useState("");
  const [actor, setActor] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [page, setPage] = useState(1);
  const key = useMemo(
    () => `${caseId}|${eventType}|${actor}|${since}|${until}|${page}`,
    [caseId, eventType, actor, since, until, page],
  );
  const query = useApiQuery(key, () =>
    fetchAudit({
      page,
      page_size: 50,
      case_id: caseId || undefined,
      event_type: eventType || undefined,
      actor_id: actor || undefined,
      since: since ? new Date(since).toISOString() : undefined,
      until: until ? new Date(until).toISOString() : undefined,
    }),
  );

  return (
    <AppShell title="Audit">
      <div className="mb-6 grid gap-3 md:grid-cols-5">
        <input
          placeholder="Case ID"
          className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm"
          value={caseId}
          onChange={(event) => {
            setPage(1);
            setCaseId(event.target.value);
          }}
        />
        <input
          placeholder="Event type"
          className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm"
          value={eventType}
          onChange={(event) => {
            setPage(1);
            setEventType(event.target.value);
          }}
        />
        <input
          placeholder="Actor"
          className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm"
          value={actor}
          onChange={(event) => {
            setPage(1);
            setActor(event.target.value);
          }}
        />
        <input
          type="datetime-local"
          className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm"
          value={since}
          onChange={(event) => setSince(event.target.value)}
        />
        <input
          type="datetime-local"
          className="rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm"
          value={until}
          onChange={(event) => setUntil(event.target.value)}
        />
      </div>
      {query.status === "loading" ? <Skeleton className="h-64" /> : null}
      {query.status === "error" ? (
        <ErrorBanner message={query.error.message} onRetry={query.reload} />
      ) : null}
      {query.status === "success" && query.data.items.length === 0 ? (
        <EmptyState title="No audit events" body="No rows matched these filters in PostgreSQL." />
      ) : null}
      {query.status === "success" && query.data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-2xl border border-white/10">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-ink-800 text-xs uppercase text-slate-400">
              <tr>
                {["Time", "Actor", "Event", "From", "To", "Summary", "Correlation", "Idempotency"].map(
                  (header) => (
                    <th key={header} className="px-3 py-3">
                      {header}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((row) => (
                <tr key={row.id} className="border-t border-white/5">
                  <td className="px-3 py-2 text-slate-400">{formatDateTime(row.timestamp)}</td>
                  <td className="px-3 py-2">
                    {row.actor_type}
                    {row.actor_id ? `/${row.actor_id}` : ""}
                  </td>
                  <td className="px-3 py-2">{row.event_type}</td>
                  <td className="px-3 py-2">{row.previous_state || "—"}</td>
                  <td className="px-3 py-2">{row.new_state || "—"}</td>
                  <td className="max-w-sm px-3 py-2 text-slate-300">{row.summary}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{row.correlation_id || "—"}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{row.idempotency_key || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex justify-end gap-2 p-3 text-sm">
            <button type="button" disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
              Previous
            </button>
            <button
              type="button"
              disabled={page * query.data.page_size >= query.data.total}
              onClick={() => setPage((n) => n + 1)}
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
