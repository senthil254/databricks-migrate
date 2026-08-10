import { useEffect, useLayoutEffect, useRef, useState } from "react";

export interface ContextMenuItem {
  label: string;
  onSelect: () => void;
}

interface Props {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}

// Minimal, reusable right-click context menu — not tied to any one tree.
// Closes on outside click or Escape. Positioned absolutely at the
// coordinates the caller captured from the triggering onContextMenu event.
export function ContextMenu({ x, y, items, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  // Start at the raw click point, then correct after measuring. A single-item
  // "Refresh" menu never needed this, but a four-item menu opened low in the
  // rail runs off the bottom of the viewport and the last item is unclickable.
  const [pos, setPos] = useState({ x, y });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const margin = 8;
    setPos({
      x: Math.max(margin, Math.min(x, window.innerWidth - width - margin)),
      y: Math.max(margin, Math.min(y, window.innerHeight - height - margin)),
    });
  }, [x, y, items.length]);

  useEffect(() => {
    function handlePointerDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="context-menu"
      style={{ position: "fixed", top: pos.y, left: pos.x, zIndex: 1000 }}
      role="menu"
    >
      {items.map((item, i) => (
        <button
          key={`${item.label}-${i}`}
          role="menuitem"
          className="context-menu-item"
          onClick={(e) => {
            // The menu renders INSIDE the clickable leaf row, whose own
            // onClick opens the preview pane (G19). Without this, choosing
            // "Migrate" would fire the migration AND open a preview — or, in
            // select mode, toggle the row's selection.
            e.stopPropagation();
            item.onSelect();
            onClose();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

// G8 fix: right-clicking a tree row (not just its tiny refresh icon) must
// open the same "Refresh" menu — matches a real SQL client (DBeaver) where
// you right-click anywhere on a catalog/schema/table row. This hook gives
// callers an onContextMenu handler for the WHOLE row plus the menu element
// to render, so RefreshControl's icon and the row itself share one trigger.
//
// G20: generalised so a node can offer the real actions its own inline
// buttons offer — "Batch migrate schema" on a schema row, "Migrate" /
// "View data" / "Copy data" on a table row. Every item calls the SAME
// handler the inline button calls; the buttons are unchanged and stay.
//
// The e.stopPropagation() is load-bearing: leaf rows now have their own
// menus, and without it a right-click on a table would ALSO open the panel
// root's menu behind it.
export function useNodeMenu(items: ContextMenuItem[]) {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  function onContextMenu(e: {
    preventDefault: () => void;
    stopPropagation?: () => void;
    clientX: number;
    clientY: number;
  }) {
    e.preventDefault();
    e.stopPropagation?.();
    setMenu({ x: e.clientX, y: e.clientY });
  }
  const menuElement =
    menu && items.length ? (
      <ContextMenu x={menu.x} y={menu.y} items={items} onClose={() => setMenu(null)} />
    ) : null;
  return { onContextMenu, menuElement };
}

// Kept as-is so every existing call site keeps working untouched.
export function useRefreshMenu(onRefresh: () => void) {
  return useNodeMenu([{ label: "Refresh", onSelect: onRefresh }]);
}
