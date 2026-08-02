import { useState, type ReactNode } from "react";
import { Icon } from "./Icon";

// G19 — one collapsible block, shared by every place that shows table data,
// function/procedure source, or transpiled SQL.
//
// Before this, each surface did its own thing: the migration card showed a
// table with no collapse at all, the chat query result likewise, and the
// routine source card was a bare <pre>. They now all use this, so the
// disclosure looks and behaves identically wherever it appears, and the
// scrolling rule is enforced in one place rather than remembered five times.
//
// The scroll box is the important part: both axes live on the content's own
// wrapper (`.pv-scroll`), never on the page — a wide table must never make the
// whole app scroll sideways.

export function Collapsible({
  title,
  meta,
  defaultOpen = true,
  children,
}: {
  title: string;
  meta?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={`pv-section ${open ? "open" : ""}`}>
      <button className="pv-section-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name="chevron" size={13} className={`pv-caret ${open ? "open" : ""}`} />
        <span className="pv-section-title">{title}</span>
        {meta && <span className="pv-section-meta">{meta}</span>}
      </button>
      {/* display-toggled rather than unmounted: collapsing must not discard
          already-fetched rows or force a refetch on re-open. */}
      <div className="pv-section-body" style={{ display: open ? "block" : "none" }}>
        {children}
      </div>
    </section>
  );
}

/** Both scrollbars, on the content's own box. `rows` caps the height at about
 *  five table rows, matching the preview pane. */
export function ScrollBox({
  children,
  variant = "default",
}: {
  children: ReactNode;
  variant?: "default" | "rows" | "code";
}) {
  const cls =
    variant === "rows" ? "pv-scroll pv-scroll-rows" : variant === "code" ? "pv-scroll pv-scroll-code" : "pv-scroll";
  return <div className={cls}>{children}</div>;
}
