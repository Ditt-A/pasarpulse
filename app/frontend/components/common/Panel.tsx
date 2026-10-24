export function Panel({
  children,
  className = "",
  title,
  eyebrow,
  action,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
  eyebrow?: string;
  action?: React.ReactNode;
}) {
  return (
    <section className={`surface shadow-panel ${className}`}>
      {(title || eyebrow || action) && (
        <div className="surface-heading">
          <div>
            {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
            {title && <h2>{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
