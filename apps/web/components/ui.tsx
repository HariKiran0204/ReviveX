export function StatusBadge({ value }: { value: string }) {
  const tone =
    value.includes("RECOVERED") && !value.includes("NOT")
      ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200"
      : value.includes("FAIL") || value.includes("BLOCK") || value.includes("REJECT")
        ? "border-rose-400/40 bg-rose-400/10 text-rose-200"
        : value.includes("APPROVAL") || value.includes("PENDING")
          ? "border-amber-400/40 bg-amber-400/10 text-amber-100"
          : "border-white/15 bg-white/5 text-slate-200";
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      {value}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-white/10 ${className}`} />;
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-rose-500/30 bg-rose-950/40 px-4 py-3 text-sm text-rose-100"
    >
      <p>{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-xs font-medium uppercase tracking-wide text-rose-200 underline"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  open,
  onCancel,
  onConfirm,
  busy,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  busy?: boolean;
}) {
  if (!open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="w-full max-w-md rounded-2xl border border-white/10 bg-ink-800 p-6"
      >
        <h2 id="confirm-title" className="font-display text-lg text-white">
          {title}
        </h2>
        <p className="mt-2 text-sm text-slate-400">{body}</p>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-lg border border-white/15 px-3 py-2 text-sm"
            onClick={onCancel}
            disabled={busy}
          >
            Back
          </button>
          <button
            type="button"
            className="rounded-lg bg-accent-500 px-3 py-2 text-sm font-medium text-ink-950 disabled:opacity-50"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
