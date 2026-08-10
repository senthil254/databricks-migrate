import { useCallback, useEffect, useRef, useState } from "react";

// G21 — a draggable width for the left rail while the data explorer is open.
//
// Why this exists: object names in the explorer are fully-qualified and often
// longer than the rail's fixed 372px, so the tail of a name is only reachable
// by scrolling horizontally. The scrollbar stays (it is the right answer for a
// single over-long row), but for a schema whose names are ALL long, scrolling
// every row one at a time is the wrong tool — widening the pane once is.
//
// The width is written to the `--rail-w-explorer` custom property on .shell
// rather than to a width style, so the existing grid rule
// (`grid-template-columns: var(--rail-w-explorer) 1fr`) keeps working
// untouched, including its media-query overrides at narrow viewports.

const STORAGE_KEY = "lakebridge.railWidth";

// DEFAULT mirrors --rail-w-explorer in theme.css. Kept in sync by hand — it is
// the reset target, so a mismatch would make double-click jump instead of
// restoring what the stylesheet ships.
export const DEFAULT_RAIL_WIDTH = 372;
export const MIN_RAIL_WIDTH = 240;

// Never let the rail eat the whole window: the work area must stay usable, so
// the ceiling is viewport-relative rather than a fixed pixel count.
function maxWidth(): number {
  if (typeof window === "undefined") return 900;
  return Math.max(MIN_RAIL_WIDTH, Math.min(900, Math.round(window.innerWidth * 0.7)));
}

function clamp(px: number): number {
  return Math.max(MIN_RAIL_WIDTH, Math.min(maxWidth(), Math.round(px)));
}

function readStored(): number {
  if (typeof window === "undefined") return DEFAULT_RAIL_WIDTH;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  const n = raw === null ? NaN : Number(raw);
  return Number.isFinite(n) ? clamp(n) : DEFAULT_RAIL_WIDTH;
}

export function useRailWidth() {
  const [width, setWidthState] = useState<number>(readStored);
  const [resizing, setResizing] = useState(false);
  // The pointer grabs the handle somewhere other than its exact centre; without
  // recording that offset the rail jumps by a few px on the first move.
  const grabOffset = useRef(0);

  const setWidth = useCallback((px: number) => {
    const next = clamp(px);
    setWidthState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      // Private mode / storage disabled: the drag still works for this
      // session, it just does not persist. Not worth surfacing.
    }
  }, []);

  const reset = useCallback(() => setWidth(DEFAULT_RAIL_WIDTH), [setWidth]);

  const startResize = useCallback(
    (clientX: number, handleLeft: number) => {
      grabOffset.current = clientX - handleLeft;
      setResizing(true);
    },
    [],
  );

  // Listeners live on window, not the handle, so the drag survives the pointer
  // outrunning the 6px handle — which it always does.
  useEffect(() => {
    if (!resizing) return;
    function onMove(e: PointerEvent) {
      e.preventDefault();
      setWidth(e.clientX - grabOffset.current);
    }
    function onUp() {
      setResizing(false);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [resizing, setWidth]);

  // A stored width that was valid on a wide monitor can exceed 70% of a small
  // one. Re-clamp on resize so the rail can never strand the work area.
  useEffect(() => {
    function onWindowResize() {
      setWidthState((w) => clamp(w));
    }
    window.addEventListener("resize", onWindowResize);
    return () => window.removeEventListener("resize", onWindowResize);
  }, []);

  return { width, resizing, startResize, setWidth, reset };
}
