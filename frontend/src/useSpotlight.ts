import { useCallback, useRef } from "react";

// G17 — cursor-follow spotlight, the motion signature carried over from the
// reference design. Sets --mx/--my as percentages on the hovered element; the
// CSS then paints a radial-gradient at that point (see .card-spotlight in
// index.css).
//
// Written to touch the DOM directly rather than via React state on purpose:
// this fires on every mousemove, and a setState per frame would re-render the
// whole card subtree. Writing a custom property is cheap and doesn't trigger
// React work at all.

export function useSpotlight<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T | null>(null);
  const frame = useRef<number | null>(null);

  const onMouseMove = useCallback((e: React.MouseEvent<T>) => {
    const el = e.currentTarget;
    const x = e.clientX;
    const y = e.clientY;

    // Coalesce to one write per animation frame — mousemove can fire far more
    // often than the compositor paints.
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      el.style.setProperty("--mx", `${((x - rect.left) / rect.width) * 100}%`);
      el.style.setProperty("--my", `${((y - rect.top) / rect.height) * 100}%`);
    });
  }, []);

  const onMouseLeave = useCallback((e: React.MouseEvent<T>) => {
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
    // Park the spotlight centred so the fade-out doesn't jump to a stale corner.
    e.currentTarget.style.setProperty("--mx", "50%");
    e.currentTarget.style.setProperty("--my", "50%");
  }, []);

  // Spread onto any element that also carries the .card-spotlight class.
  return { ref, spotlightProps: { onMouseMove, onMouseLeave } };
}
