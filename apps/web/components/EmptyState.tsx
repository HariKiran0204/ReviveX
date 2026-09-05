export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/15 bg-ink-800/40 px-8 py-16 text-center">
      <h2 className="font-display text-lg text-white">{title}</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-400">{body}</p>
    </div>
  );
}
