import { useState } from "react";
import { DRAG_MIME, decodeDrag, type DragObject } from "./dragTypes";
import { Icon } from "./Icon";

interface Props {
  onDropObject: (obj: DragObject) => void;
}

export function TargetDropZone({ onDropObject }: Props) {
  const [hover, setHover] = useState(false);

  return (
    <div
      className={`target-zone ${hover ? "target-zone-hover" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DRAG_MIME)) {
          e.preventDefault();
          setHover(true);
        }
      }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setHover(false);
        const raw = e.dataTransfer.getData(DRAG_MIME);
        const obj = raw ? decodeDrag(raw) : null;
        if (obj) onDropObject(obj);
      }}
    >
      <div className="target-zone-icon">
        <Icon name="catalog" size={30} />
      </div>
      <div>
        <strong>Databricks target zone</strong>
        <p className="muted">
          Drop a real Redshift or Starburst object here. Tables and views create the destination
          object <em>and</em> copy their rows; functions and procedures migrate their DDL only.
          Target catalog/schema is chosen by the backend (see <code className="mono">migrate.py</code>).
        </p>
      </div>
    </div>
  );
}
