// Shared drag-payload shape between the tree nodes and the target drop
// zone. Kept as its own module so both sides agree on the contract.

export type SourceSystem = "redshift" | "starburst";

export type DraggableObjectType = "table" | "view" | "procedure" | "function" | "udf";

export interface DragObject {
  system: SourceSystem;
  objectType: DraggableObjectType;
  // Redshift: schema + name. Starburst: catalog + schema + name.
  catalog?: string;
  schema: string;
  name: string;
}

export const DRAG_MIME = "application/x-lakebridge-object";

export function encodeDrag(obj: DragObject): string {
  return JSON.stringify(obj);
}

export function decodeDrag(raw: string): DragObject | null {
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.system === "string" && typeof parsed.name === "string") {
      return parsed as DragObject;
    }
    return null;
  } catch {
    return null;
  }
}

// G3.4 — stable identity key for a DragObject, used to track multi-select
// state for the explicit-batch flow without duplicating object identity
// logic in every tree component.
export function dragKey(obj: DragObject): string {
  return `${obj.system}|${obj.catalog ?? ""}|${obj.schema}|${obj.name}|${obj.objectType}`;
}
