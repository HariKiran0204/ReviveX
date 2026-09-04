"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ErrorBanner, Skeleton } from "@/components/ui";
import { fetchPolicy, updatePolicy } from "@/lib/api";
import type { PolicySettings } from "@/lib/api/types";
import { validatePolicySettings } from "@/lib/policy";
import { useApiQuery } from "@/lib/useApiQuery";

export default function PoliciesPage() {
  const query = useApiQuery("policy", fetchPolicy);
  const toast = useToast();
  const [draft, setDraft] = useState<PolicySettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query.status === "success") {
      setDraft(query.data.policy);
    }
  }, [query.status, query]);

  async function save() {
    if (!draft) {
      return;
    }
    const problem = validatePolicySettings(draft);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await updatePolicy(draft);
      setDraft(next.policy);
      toast("Policy saved; refreshed from backend");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Save failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="Policies">
      <p className="mb-6 max-w-2xl text-sm text-slate-400">
        Merchant settings are stored in PostgreSQL and merged into PolicyEngine. The UI cannot
        bypass backend enforcement.
      </p>
      {query.status === "loading" ? <Skeleton className="h-80" /> : null}
      {query.status === "error" ? (
        <ErrorBanner message={query.error.message} onRetry={query.reload} />
      ) : null}
      {draft ? (
        <form
          className="grid max-w-3xl gap-4 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Field
            label="Max retries"
            value={String(draft.max_retry_attempts)}
            onChange={(value) => setDraft({ ...draft, max_retry_attempts: Number(value) })}
          />
          <Field
            label="Max discount %"
            value={draft.max_discount_percent}
            onChange={(value) => setDraft({ ...draft, max_discount_percent: value })}
          />
          <Field
            label="Daily discount budget"
            value={draft.max_daily_discount_budget}
            onChange={(value) => setDraft({ ...draft, max_daily_discount_budget: value })}
          />
          <Field
            label="High-value approval"
            value={draft.high_value_approval_threshold}
            onChange={(value) => setDraft({ ...draft, high_value_approval_threshold: value })}
          />
          <Field
            label="Medium-value approval"
            value={draft.medium_value_approval_threshold}
            onChange={(value) => setDraft({ ...draft, medium_value_approval_threshold: value })}
          />
          <Field
            label="Communications / day"
            value={String(draft.max_communications_per_day)}
            onChange={(value) => setDraft({ ...draft, max_communications_per_day: Number(value) })}
          />
          <label className="md:col-span-2 text-xs text-slate-400">
            Blocked actions (comma-separated)
            <input
              className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-white"
              value={draft.blocked_action_types.join(",")}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  blocked_action_types: event.target.value
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={draft.automatic_recovery_enabled}
              onChange={(event) =>
                setDraft({ ...draft, automatic_recovery_enabled: event.target.checked })
              }
            />
            Automatic recovery enabled
          </label>
          {error ? <p className="md:col-span-2 text-sm text-rose-300">{error}</p> : null}
          <div className="md:col-span-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-accent-500 px-4 py-2 text-sm font-medium text-ink-950 disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save policy"}
            </button>
          </div>
        </form>
      ) : null}
    </AppShell>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-xs text-slate-400">
      {label}
      <input
        className="mt-1 w-full rounded-lg border border-white/10 bg-ink-800 px-3 py-2 text-sm text-white"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
