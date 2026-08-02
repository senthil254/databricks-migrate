import { useEffect, useRef } from "react";

// G5 — minimal, dependency-free confirm-dialog focus management.
// The prior implementation (plain conditionally-rendered divs in
// Explorer.tsx) had no dialog role, no focus trap, no initial focus, and
// never returned focus to the element that opened it — a real WCAG 2.1.3
// (focus order) / 2.4.3 (focus not lost) gap, not a hypothetical one.
//
// Pattern used: native focus save/restore + a simple Tab-cycling trap,
// per the task's instruction to avoid a heavy new dependency when one
// isn't already installed (checked: no focus-trap/react-aria/etc. in
// package.json).
export function ConfirmDialog({
  titleId,
  title,
  children,
  onCancel,
  onConfirm,
  confirmLabel,
}: {
  titleId: string;
  title: string;
  children: React.ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel: string;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    // Focus the confirm button on open (not the more-destructive default
    // path a screen-reader/keyboard user would otherwise have to find).
    confirmBtnRef.current?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const container = dialogRef.current;
      if (!container) return;
      const focusable = Array.from(
        container.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Restore focus to whatever triggered the dialog (the row's
      // button/link), not just document.body.
      previouslyFocused.current?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={dialogRef}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id={titleId}>{title}</h3>
        {children}
        <div className="modal-actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" ref={confirmBtnRef} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
