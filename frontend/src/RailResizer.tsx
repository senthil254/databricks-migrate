import { DEFAULT_RAIL_WIDTH, MIN_RAIL_WIDTH } from "./useRailWidth";

interface Props {
  width: number;
  resizing: boolean;
  onStart: (clientX: number, handleLeft: number) => void;
  onSetWidth: (px: number) => void;
  onReset: () => void;
}

// G21 — the drag handle that widens the left rail, sitting on its right edge
// exactly where the rail meets the work area.
//
// Deliberately NOT a replacement for the explorer's horizontal scrollbar: that
// still handles one unusually long row inside a normally-sized pane. This
// handles the other case — a whole schema of long names, where widening once
// beats scrolling every row.
//
// Operable three ways, because a 6px drag target alone is not accessible:
//   * drag
//   * arrow keys when focused (Shift for a coarse step)
//   * double-click, or Home, to restore the stylesheet's default
const STEP = 16;
const COARSE_STEP = 64;

export function RailResizer({ width, resizing, onStart, onSetWidth, onReset }: Props) {
  return (
    <div
      className={`rail-resizer ${resizing ? "resizing" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the data explorer pane"
      aria-valuenow={width}
      aria-valuemin={MIN_RAIL_WIDTH}
      tabIndex={0}
      title="Drag to resize the explorer · double-click to reset"
      onPointerDown={(e) => {
        // Left button only: a right-click here belongs to the panel behind it,
        // and a middle-click paste-scroll would start a phantom drag.
        if (e.button !== 0) return;
        // preventDefault stops the drag from selecting text across the app,
        // but it also suppresses the focus this element would otherwise get
        // from the click — so focus it explicitly. Without this the arrow-key
        // path is reachable only by tabbing to it, which nobody does after
        // grabbing the handle with the mouse.
        e.preventDefault();
        e.currentTarget.focus();
        onStart(e.clientX, e.currentTarget.getBoundingClientRect().left);
      }}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        const step = e.shiftKey ? COARSE_STEP : STEP;
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          onSetWidth(width - step);
        } else if (e.key === "ArrowRight") {
          e.preventDefault();
          onSetWidth(width + step);
        } else if (e.key === "Home") {
          e.preventDefault();
          onReset();
        }
      }}
    >
      {/* The visible grip. The hit area is the whole 10px-wide parent, which is
          larger than the 2px line people actually aim at — a hairline that is
          only grabbable on its exact pixel is the usual failure here. */}
      <span className="rail-resizer-grip" aria-hidden="true" />
    </div>
  );
}

export { DEFAULT_RAIL_WIDTH };
