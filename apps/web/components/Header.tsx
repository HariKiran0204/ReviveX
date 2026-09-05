import { HealthStatus } from "@/components/HealthStatus";

export function Header({ title }: { title: string }) {
  return (
    <header className="flex items-center justify-between border-b border-white/10 bg-ink-900/80 px-8 py-4 backdrop-blur">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-accent-400">
          Autonomous Revenue Recovery
        </p>
        <h1 className="mt-1 font-display text-xl text-white">{title}</h1>
      </div>
      <div className="flex items-center gap-3">
        <span className="hidden rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-wide text-slate-400 sm:inline">
          Local
        </span>
        <HealthStatus />
      </div>
    </header>
  );
}
