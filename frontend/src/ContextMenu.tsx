import { useEffect, useRef, useState } from "react";

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
      style={{ position: "fixed", top: y, left: x, zIndex: 1000 }}
      role="menu"
    >
      {items.map((item) => (
        <button
          key={item.label}
          role="menuitem"
          className="context-menu-item"
          onClick={() => {
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
export function useRefreshMenu(onRefresh: () => void) {
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  function onContextMenu(e: { preventDefault: () => void; stopPropagation?: () => void; clientX: number; clientY: number }) {
    e.preventDefault();
    e.stopPropagation?.();
    setMenu({ x: e.clientX, y: e.clientY });
  }
  const menuElement = menu ? (
    <ContextMenu x={menu.x} y={menu.y} items={[{ label: "Refresh", onSelect: onRefresh }]} onClose={() => setMenu(null)} />
  ) : null;
  return { onContextMenu, menuElement };
}
