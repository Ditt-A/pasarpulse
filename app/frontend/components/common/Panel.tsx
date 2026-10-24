export function Panel({ children, className = "", title, eyebrow, action }: { children: React.ReactNode; className?: string; title?: string; eyebrow?: string; action?: React.ReactNode }) {
  return <section className={`rounded-2xl border border-line/80 bg-panel/90 shadow-panel ${className}`}>
    {(title || eyebrow || action) && <div className="flex items-start justify-between gap-4 border-b border-line/70 px-4 py-3">
      <div>{eyebrow && <div className="mb-1 text-[10px] font-semibold uppercase tracking-[.16em] text-cyanpulse/80">{eyebrow}</div>}{title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}</div>{action}
    </div>}
    {children}
  </section>;
}
