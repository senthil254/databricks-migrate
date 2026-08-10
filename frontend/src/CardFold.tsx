import { Icon } from "./Icon";

// G21 — the collapse/expand affordance in a card's top-right corner.
//
// Both the batch cards and the chat plan cards stack vertically and each one
// is tall, so a session with several of them turns into a long scroll where
// the thing you want is off-screen. Collapsing the ones you are done with is
// the fix. Same control in both places on purpose: two different-looking
// toggles for the same job is worse than none.
//
// Icon-only, but it carries a real accessible name and aria-expanded, so it
// is not a mystery glyph to a screen reader. Positioned absolutely by
// `.card-fold` against the card, which is why every card using it must be
// `position: relative`.

export function CardFold({
  open,
  onToggle,
  label,
}: {
  open: boolean;
  onToggle: () => void;
  /** What is being collapsed, e.g. "batch batch_81" — becomes the a11y name. */
  label: string;
}) {
  return (
    <button
      className="card-fold"
      aria-expanded={open}
      aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
      title={open ? "Collapse" : "Expand"}
      onClick={(e) => {
        // These cards sit inside clickable surfaces in places; keep the
        // toggle from doubling as a click on whatever is behind it.
        e.stopPropagation();
        onToggle();
      }}
    >
      <Icon name="chevron" size={14} className={`card-fold-caret ${open ? "open" : ""}`} />
    </button>
  );
}
