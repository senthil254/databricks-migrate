import { useEffect, useState } from "react";
import { usePreview } from "./PreviewPane";
import { explorerApi, type RedshiftRoutine, type RedshiftTable } from "./explorerApi";
import { DRAG_MIME, encodeDrag, type DragObject } from "./dragTypes";
import { useRefreshMenu } from "./ContextMenu";
import { Icon } from "./Icon";

// G8 — refresh icon; the same onRefresh is also wired to a right-click
// anywhere on the row via useRefreshMenu in each row-owning component below
// (real SQL clients like DBeaver let you right-click the whole row, not
// just a tiny icon). Clears the caller's cached children state so the
// existing "fetch once, cache in state" effect naturally re-fires, only
// re-fetching that node's direct children, not the whole tree.
function RefreshControl({ onRefresh, label }: { onRefresh: () => void; label: string }) {
  return (
    <button
      className="mini-btn"
      onClick={(e) => {
        e.stopPropagation();
        onRefresh();
      }}
      title={`Refresh ${label} (re-fetch just this node's children; right-click the row for the same action)`}
      aria-label={`Refresh ${label}`}
    >
      <Icon name="refresh" size={13} />
    </button>
  );
}

interface Props {
  onRequestDataCopy: (schema: string, table: string) => void;
  onRequestSchemaBatch?: (schema: string) => void;
  // G5 — keyboard-operable alternative to HTML5 drag-and-drop. Native
  // drag-and-drop (draggable/onDragStart/onDrop) has no keyboard
  // equivalent — confirmed here, not assumed: the row is a plain <div>,
  // not focusable, with no keydown handler. Reuses the exact same
  // Explorer.runDdlMigration -> /migrate/* call the drag path uses.
  onRequestDdlMigration?: (obj: DragObject) => void;
  selectMode?: boolean;
  isSelected?: (obj: DragObject) => boolean;
  onToggleSelect?: (obj: DragObject) => void;
  // G9.1 — real source-side preview (schema/table only; routines have no rows).
  onRequestPreview?: (schema: string, table: string) => void;
  // G15 Phase A — real routine source view (procedure/function only).
  onRequestSource?: (schema: string, name: string, routineType: string) => void;
}

// G15 Phase A — small colored per-row-type glyph, restyled tree rows.
function TypeGlyph({ kind }: { kind: "table" | "view" | "routine" }) {
  const icon = kind === "table" ? "table" : kind === "view" ? "view" : "function";
  return (
    <span className={`type-glyph type-glyph-${kind}`} aria-hidden="true">
      <Icon name={icon} size={13} />
    </span>
  );
}

// G15 Phase A — column-level expansion under a table/view row, rendered as
// indented leaf rows with inline datatype badges (e.g. `grantee` `varchar`),
// reusing the existing columns fetch that was previously wired but not
// exposed at this level of the tree.
function ColumnsList({ columns }: { columns: { name: string; data_type: string }[] | null }) {
  if (columns === null) return <p className="empty column-loading">loading columns…</p>;
  return (
    <div className="columns-list">
      {columns.map((c) => (
        <div className="column-row" key={c.name}>
          <span className="column-name mono">{c.name}</span>
          <span className="column-type-badge">{c.data_type}</span>
        </div>
      ))}
    </div>
  );
}

function DraggableRow({
  obj,
  label,
  sub,
  glyph,
  selectMode,
  selected,
  onToggleSelect,
  onRequestDdlMigration,
  extraActions,
  columnsToggle,
}: {
  obj: DragObject;
  label: string;
  sub: string;
  glyph?: "table" | "view" | "routine";
  selectMode?: boolean;
  selected?: boolean;
  onToggleSelect?: (obj: DragObject) => void;
  onRequestDdlMigration?: (obj: DragObject) => void;
  extraActions?: React.ReactNode;
  columnsToggle?: React.ReactNode;
}) {
  const { openPreview } = usePreview();
  return (
    <div className="tree-leaf-row">
      <div
        className="tree-leaf"
        draggable={!selectMode}
        onDragStart={(e) => {
          e.dataTransfer.setData(DRAG_MIME, encodeDrag(obj));
          e.dataTransfer.effectAllowed = "copy";
        }}
        // G19: clicking the row opens the preview, matching the eye button.
        // The eye button stays — this is an additional way in, not a
        // replacement. Drag is unaffected: a real drag suppresses the click.
        onClick={
          selectMode
            ? () => onToggleSelect?.(obj)
            : () =>
                openPreview(
                  obj.objectType === "table" || obj.objectType === "view"
                    ? { kind: "table", system: "redshift", schema: obj.schema, name: obj.name }
                    : {
                        kind: "routine",
                        system: "redshift",
                        schema: obj.schema,
                        name: obj.name,
                        routineType: obj.objectType.toUpperCase(),
                      },
                )
        }
        /* G19: `title` removed deliberately — leaving it would show the OS's
           ~1s-delayed tooltip on top of the instant one. All of its text moved
           into data-tip, which useInstantTip renders immediately. */
        data-tip={
          selectMode
            ? `Click to select ${obj.schema}.${obj.name} for batch`
            : `${obj.schema}.${obj.name} · ${obj.objectType} — drag onto the Databricks target to migrate`
        }
      >
        {selectMode && (
          <input
            type="checkbox"
            checked={!!selected}
            readOnly
            aria-label={`Select ${label} (${sub}) for batch`}
            onClick={(e) => e.stopPropagation()}
            onChange={() => onToggleSelect?.(obj)}
          />
        )}
        {columnsToggle}
        {glyph ? <TypeGlyph kind={glyph} /> : <span className="tree-leaf-icon" aria-hidden="true"><Icon name="drag" size={13} /></span>}
        <span className="tree-leaf-label">{label}</span>
        <span className="tree-leaf-sub">{sub}</span>
      </div>
      {!selectMode && onRequestDdlMigration && (
        <button
          className="mini-btn"
          onClick={() => onRequestDdlMigration(obj)}
          title={`Keyboard-operable alternative to drag: migrate ${label}'s DDL the same way a drop would`}
        >
          migrate
        </button>
      )}
      {!selectMode && extraActions}
    </div>
  );
}

// G15 Phase A — wraps DraggableRow with a caret to lazily expand column-
// level detail (reuses the existing redshiftColumns fetch, just newly
// wired into the tree UI instead of only the batch/preview paths).
function TableRowWithColumns(props: Parameters<typeof DraggableRow>[0] & { schema: string; table: string }) {
  const [open, setOpen] = useState(false);
  const [columns, setColumns] = useState<{ name: string; data_type: string }[] | null>(null);

  useEffect(() => {
    if (!open || columns !== null) return;
    explorerApi
      .redshiftColumns(props.schema, props.table)
      .then(setColumns)
      .catch(() => setColumns([]));
  }, [open, props.schema, props.table, columns]);

  return (
    <div className="table-row-with-columns">
      <DraggableRow
        {...props}
        columnsToggle={
          <button
            className="tree-caret-btn"
            onClick={(e) => {
              e.stopPropagation();
              setOpen((o) => !o);
            }}
            title="Show/hide columns"
            aria-label={`Toggle columns for ${props.label}`}
          >
            <span className={`tree-caret ${open ? "open" : ""}`}>
              <Icon name="chevron" size={12} />
            </span>
          </button>
        }
      />
      {open && <ColumnsList columns={columns} />}
    </div>
  );
}

function SchemaNode({
  schema,
  onRequestDataCopy,
  onRequestSchemaBatch,
  onRequestDdlMigration,
  onRequestPreview,
  onRequestSource,
  selectMode,
  isSelected,
  onToggleSelect,
}: {
  schema: string;
  onRequestDataCopy: Props["onRequestDataCopy"];
  onRequestSchemaBatch?: Props["onRequestSchemaBatch"];
  onRequestDdlMigration?: Props["onRequestDdlMigration"];
  onRequestPreview?: Props["onRequestPreview"];
  onRequestSource?: Props["onRequestSource"];
  selectMode?: boolean;
  isSelected?: Props["isSelected"];
  onToggleSelect?: Props["onToggleSelect"];
}) {
  const [open, setOpen] = useState(false);
  const [tables, setTables] = useState<RedshiftTable[] | null>(null);
  const [routines, setRoutines] = useState<RedshiftRoutine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || tables !== null) return;
    Promise.all([explorerApi.redshiftTables(schema), explorerApi.redshiftRoutines(schema)])
      .then(([t, r]) => {
        setTables(t);
        setRoutines(r);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, schema, tables]);

  const refresh = () => {
    setTables(null);
    setRoutines(null);
    setError(null);
  };
  const { onContextMenu, menuElement } = useRefreshMenu(refresh);

  return (
    <div className="tree-node">
      <div className="tree-toggle-row" onContextMenu={onContextMenu}>
        <button className="tree-toggle" onClick={() => setOpen((o) => !o)}>
          <span className={`tree-caret ${open ? "open" : ""}`}>
            <Icon name="chevron" size={12} />
          </span>{" "}
          {schema}
        </button>
        <RefreshControl label={`schema ${schema}`} onRefresh={refresh} />
        {menuElement}
        {onRequestSchemaBatch && (
          <button
            className="mini-btn batch-btn"
            onClick={() => onRequestSchemaBatch(schema)}
            title="Migrate every real object in this schema in one batch (distinct from single-object drag-and-drop)"
          >
            batch migrate schema
          </button>
        )}
      </div>
      {open && (
        <div className="tree-children">
          {error && <p className="error">{error}</p>}
          {tables === null && !error && <p className="empty">Loading…</p>}
          {tables?.map((t) => {
            const isView = t.type === "view";
            const obj: DragObject = { system: "redshift", objectType: isView ? "view" : "table", schema, name: t.name };
            return (
              <TableRowWithColumns
                key={t.name}
                schema={schema}
                table={t.name}
                obj={obj}
                label={t.name}
                sub={t.type}
                glyph={isView ? "view" : "table"}
                selectMode={selectMode}
                selected={isSelected?.(obj)}
                onToggleSelect={onToggleSelect}
                onRequestDdlMigration={onRequestDdlMigration}
                extraActions={
                  <>
                    {onRequestPreview && (
                      <button
                        className="mini-btn"
                        onClick={() => onRequestPreview(schema, t.name)}
                        title={`Preview real rows in ${schema}.${t.name}`}
                        aria-label={`Preview ${t.name}`}
                      >
                        <Icon name="eye" size={14} />
                      </button>
                    )}
                    {t.type !== "view" && (
                      <button
                        className="mini-btn"
                        onClick={() => onRequestDataCopy(schema, t.name)}
                        title="Copy real row data to Databricks (separate from DDL migration)"
                      >
                        copy data
                      </button>
                    )}
                  </>
                }
              />
            );
          })}
          {routines?.map((r) => {
            const obj: DragObject = { system: "redshift", objectType: r.type === "PROCEDURE" ? "procedure" : "function", schema, name: r.name };
            return (
              <DraggableRow
                key={r.name}
                obj={obj}
                label={r.name}
                sub={r.type}
                glyph="routine"
                selectMode={selectMode}
                selected={isSelected?.(obj)}
                onToggleSelect={onToggleSelect}
                onRequestDdlMigration={onRequestDdlMigration}
                extraActions={
                  onRequestSource && (
                    <button
                      className="mini-btn"
                      onClick={() => onRequestSource(schema, r.name, r.type)}
                      title={`View real source for ${schema}.${r.name}`}
                      aria-label={`View source ${r.name}`}
                    >
                      <Icon name="eye" size={14} />
                    </button>
                  )
                }
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export function RedshiftTree({
  onRequestDataCopy,
  onRequestSchemaBatch,
  onRequestDdlMigration,
  selectMode,
  isSelected,
  onToggleSelect,
}: Props) {
  const [databases, setDatabases] = useState<string[] | null>(null);
  const [schemas, setSchemas] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // G19 — the eye button used to open a preview inside this tree. It now opens
  // the centre-pane <PreviewPane>; the tree keeps no preview state of its own.
  const { openPreview } = usePreview();

  useEffect(() => {
    if (databases !== null || schemas !== null) return;
    Promise.all([explorerApi.redshiftDatabases(), explorerApi.redshiftSchemas()])
      .then(([d, s]) => {
        setDatabases(d.map((x) => x.name));
        setSchemas(s.map((x) => x.name));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [databases, schemas]);

  const refreshRoot = () => {
    setDatabases(null);
    setSchemas(null);
    setError(null);
  };
  const { onContextMenu: onRootContextMenu, menuElement: rootMenuElement } = useRefreshMenu(refreshRoot);

  return (
    <div className="source-panel redshift-panel" onContextMenu={onRootContextMenu}>
      <h3>
        <span className="engine-dot lakebridge" /> Redshift <span className="engine-tag">lakebridge-transpile (deterministic)</span>
        <RefreshControl label="Redshift root (databases/schemas)" onRefresh={refreshRoot} />
        {rootMenuElement}
      </h3>
      {error && <p className="error">{error}</p>}
      {databases && <p className="muted mono">databases: {databases.join(", ") || "(none)"}</p>}
      {schemas === null && !error && <p className="empty">Loading real schemas…</p>}
      {schemas?.map((s) => (
        <SchemaNode
          key={s}
          schema={s}
          onRequestDataCopy={onRequestDataCopy}
          onRequestSchemaBatch={onRequestSchemaBatch}
          onRequestDdlMigration={onRequestDdlMigration}
          onRequestPreview={(schema, table) =>
            openPreview({ kind: "table", system: "redshift", schema, name: table })
          }
          onRequestSource={(schema, name, routineType) =>
            openPreview({ kind: "routine", system: "redshift", schema, name, routineType })
          }
          selectMode={selectMode}
          isSelected={isSelected}
          onToggleSelect={onToggleSelect}
        />
      ))}
    </div>
  );
}
