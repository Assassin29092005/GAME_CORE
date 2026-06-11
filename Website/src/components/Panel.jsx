// HUD panel with corner-bracket frame. variant: "" | "live" (teal) | "threat" (ember)
export default function Panel({ title, tag, variant = "", className = "", children }) {
  return (
    <section className={`panel ${variant} ${className}`}>
      <span className="c tl" />
      <span className="c tr" />
      <span className="c bl" />
      <span className="c br" />
      {(title || tag) && (
        <header className="panel-head">
          <h2 className="panel-title">{title}</h2>
          {tag && <span className="panel-tag">{tag}</span>}
        </header>
      )}
      {children}
    </section>
  );
}
