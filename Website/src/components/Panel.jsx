// Editorial section block. Title, optional kicker tag, optional warm variant
// (the radar pane uses warm — feels like ink on cream paper).
export default function Panel({ title, tag, variant = "", className = "", children }) {
  return (
    <section className={`block ${variant} ${className}`}>
      {(title || tag) && (
        <header className="block-head">
          <h2 className="block-title">{title}</h2>
          {tag && <span className="block-tag">{tag}</span>}
        </header>
      )}
      {children}
    </section>
  );
}
