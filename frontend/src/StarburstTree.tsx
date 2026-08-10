import { useEffect, useState } from "react";
import { usePreview } from "./PreviewPane";
import { explorerApi, type StarburstTable, type StarburstUdf } from "./explorerApi";
import { DRAG_MIME, encodeDrag, type DragObject } from "./dragTypes";
import { SHOW_EXPERIMENTAL_STARBURST } from "./featureFlags";
import { useNodeMenu, useRefreshMenu, type ContextMenuItem } from "./ContextMenu";
import { Icon } from "./Icon";

// G15 Phase A — small colored per-row-type glyph, mirroring RedshiftTree.
function TypeGlyph({ kind }: { kind: "table" | "view" | "udf" }) {
  const icon = kind === "table" ? "table" : kind === "view" ? "view" : "function";
  return (
    <span className={`type-glyph type-glyph-${kind === "udf" ? "routine" : kind}`} aria-hidden="true">
      <Icon name={icon} size={13} />
    </span>
  );
}

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

// G8 — refresh icon; the same onRefresh is also wired to a right-click
// anywhere on the row via useRefreshMenu in each row-owning component below
// (real SQL clients like DBeaver let you right-click the whole row, not
// just a tiny icon — the icon alone was not enough). Clears the caller's
// cached children state so the existing "fetch once, cache in state"
// effect naturally re-fires, only re-fetching that node's direct children.
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

interface TreeProps {
  selectMode?: boolean;
  isSelected?: (obj: DragObject) => boolean;
  onToggleSelect?: (obj: DragObject) => void;
  // G5 — same keyboard-operable drag alternative as RedshiftTree.tsx;
  // reuses the exact same Explorer.runDdlMigration call the drag path uses.
  onRequestDdlMigration?: (obj: DragObject) => void;
  // G7 — always-visible, deterministic, non-LLM DDL migration path.
  onRequestDdlMigrationCustom?: (obj: DragObject) => void;
  // G7 — real row-data copy, tables only.
  onRequestDataCopy?: (catalog: string, schema: string, table: string) => void;
  // G9 — batch migrate every table/view in a Starburst schema, mirrors
  // RedshiftTree's onRequestSchemaBatch but needs catalog too.
  onRequestSchemaBatch?: (catalog: string, schema: string) => void;
  // G9.1 — real source-side preview.
  onRequestPreview?: (catalog: string, schema: string, table: string) => void;
}

function DraggableRow({
  obj,
  label,
  sub,
  warnReason,
  selectMode,
  selected,
  onToggleSelect,
  onRequestDdlMigration,
  onRequestDdlMigrationCustom,
  onRequestDataCopy,
  onRequestPreview,
  isTable,
  canPreview,
  glyph,
  columnsToggle,
  onRequestUdfSource,
}: {
  obj: DragObject;
  label: string;
  sub: string;
  warnReason?: string;
  selectMode?: boolean;
  selected?: boolean;
  onToggleSelect?: (obj: DragObject) => void;
  onRequestDdlMigration?: (obj: DragObject) => void;
  onRequestDdlMigrationCustom?: (obj: DragObject) => void;
  onRequestDataCopy?: (catalog: string, schema: string, table: string) => void;
  onRequestPreview?: (catalog: string, schema: string, table: string) => void;
  isTable?: boolean;
  // G17 Stage 1 — the eye/preview button is offered for tables AND views
  // (a view preview is a plain SELECT, same as a table). Deliberately
  // separate from `isTable` (which still gates "copy data"); UDFs get a
  // source view rather than a data preview.
  canPreview?: boolean;
  glyph?: "table" | "view" | "udf";
  columnsToggle?: React.ReactNode;
  // G18 — corrected: Starburst UDF bodies ARE retrievable. The earlier claim
  // that Trino has no SHOW CREATE FUNCTION was wrong for this server, and the
  // UI was showing a fabricated stub. This now fetches the real source.
  onRequestUdfSource?: (name: string) => void;
}) {
  const { openPreview } = usePreview();

  // G20 — right-click path to the SAME handlers the inline mini-btns below
  // call. Purely additive: every button stays exactly as it was, and the
  // conditions here are copied one-for-one from those buttons so the menu
  // can never offer an action the row doesn't actually support.
  // NOTE: "Migrate (LLM)" -> onRequestDdlMigration (the slow, experimental
  // Databricks LLM job) and "Migrate" -> onRequestDdlMigrationCustom (the
  // deterministic seconds-long translator) are DELIBERATELY separate items.
  // They are different backends with wildly different runtimes; do not merge.
  const menuItems: ContextMenuItem[] = [];
  if (!selectMode && SHOW_EXPERIMENTAL_STARBURST && onRequestDdlMigration) {
    menuItems.push({ label: "Migrate (LLM)", onSelect: () => onRequestDdlMigration(obj) });
  }
  if (!selectMode && onRequestDdlMigrationCustom) {
    menuItems.push({ label: "Migrate", onSelect: () => onRequestDdlMigrationCustom(obj) });
  }
  if (!selectMode && isTable && onRequestDataCopy && obj.catalog) {
    menuItems.push({
      label: "Copy data",
      onSelect: () => onRequestDataCopy(obj.catalog as string, obj.schema, obj.name),
    });
  }
  if (!selectMode && canPreview && onRequestPreview && obj.catalog) {
    menuItems.push({
      label: "View data",
      onSelect: () => onRequestPreview(obj.catalog as string, obj.schema, obj.name),
    });
  }
  if (!selectMode && !isTable && !canPreview && onRequestUdfSource) {
    menuItems.push({ label: "View source", onSelect: () => onRequestUdfSource(label) });
  }
  const { onContextMenu, menuElement } = useNodeMenu(menuItems);

  // Deliberately still draggable even when warnReason is set (e.g. UDFs) —
  // the backend's real 400 rejection is meant to be surfaced honestly in
  // the migration card, not hidden by preemptively disabling the drag.
  // Same honesty rule applies to the keyboard "migrate" button below: it's
  // still offered for UDFs, and clicking it hits the same real 400.
  return (
    // G20: handler on the OUTER row — the migrate/copy/eye buttons are
    // siblings of .tree-leaf, so a right-click there would otherwise miss the
    // menu and bubble to the panel root's "Refresh".
    <div className="tree-leaf-row" onContextMenu={onContextMenu}>
      {menuElement}
      <div
        className={`tree-leaf ${warnReason ? "tree-leaf-warn" : ""}`}
        draggable={!selectMode}
        onDragStart={(e) => {
          e.dataTransfer.setData(DRAG_MIME, encodeDrag(obj));
          e.dataTransfer.effectAllowed = "copy";
        }}
        // G19: clicking the row opens the preview (see RedshiftTree). Tables
        // and views get their data; a UDF gets its real source SQL.
        onClick={
          selectMode
            ? () => onToggleSelect?.(obj)
            : () =>
                openPreview(
                  obj.objectType === "table" || obj.objectType === "view"
                    ? {
                        kind: "table",
                        system: "starburst",
                        catalog: obj.catalog,
                        schema: obj.schema,
                        name: obj.name,
                      }
                    : {
                        kind: "routine",
                        system: "starburst",
                        catalog: obj.catalog,
                        schema: obj.schema,
                        name: obj.name,
                        routineType: "FUNCTION",
                      },
                )
        }
        /* G19: see RedshiftTree — `title` removed so only the instant tip shows. */
        data-tip={
          selectMode
            ? `Click to select ${obj.schema}.${obj.name} for batch`
            : warnReason ??
              `${obj.catalog ? obj.catalog + "." : ""}${obj.schema}.${obj.name} · ${obj.objectType} — drag onto the Databricks target to migrate`
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
      {!selectMode && SHOW_EXPERIMENTAL_STARBURST && onRequestDdlMigration && (
        <button
          className="mini-btn"
          onClick={() => onRequestDdlMigration(obj)}
          title={`Experimental LLM transpile of ${label}'s DDL — same path a drop takes; can take 5+ minutes${warnReason ? " (will hit the same real backend rejection as dragging this row)" : ""}`}
        >
          migrate (llm)
        </button>
      )}
      {!selectMode && onRequestDdlMigrationCustom && (
        <button
          className="mini-btn"
          onClick={() => onRequestDdlMigrationCustom(obj)}
          title={`Deterministic, non-LLM DDL migration for ${label} (seconds, not minutes) — this project's own Python translator, no Lakebridge/LLM job`}
        >
          migrate
        </button>
      )}
      {!selectMode && isTable && onRequestDataCopy && obj.catalog && (
        <button
          className="mini-btn"
          onClick={() => onRequestDataCopy(obj.catalog as string, obj.schema, obj.name)}
          title="Copy real row data to Databricks (separate from DDL migration)"
        >
          copy data
        </button>
      )}
      {!selectMode && canPreview && onRequestPreview && obj.catalog && (
        <button
          className="mini-btn"
          onClick={() => onRequestPreview(obj.catalog as string, obj.schema, obj.name)}
          title={`Preview real rows in ${obj.catalog}.${obj.schema}.${obj.name}`}
          aria-label={`Preview ${obj.name}`}
        >
          <Icon name="eye" size={14} />
        </button>
      )}
      {!selectMode && !isTable && !canPreview && onRequestUdfSource && (
        <button
          className="mini-btn"
          onClick={() => onRequestUdfSource(label)}
          title="View this function's real source (SHOW CREATE FUNCTION)"
          aria-label={`View source ${label}`}
        >
          <Icon name="eye" size={14} />
        </button>
      )}
    </div>
  );
}

// G15 Phase A — lazy column expansion, mirrors RedshiftTree.tsx's version.
function TableRowWithColumns(props: Parameters<typeof DraggableRow>[0] & { catalog: string; schema: string; table: string }) {
  const [open, setOpen] = useState(false);
  const [columns, setColumns] = useState<{ name: string; data_type: string }[] | null>(null);

  useEffect(() => {
    if (!open || columns !== null) return;
    explorerApi
      .starburstColumns(props.catalog, props.schema, props.table)
      .then(setColumns)
      .catch(() => setColumns([]));
  }, [open, props.catalog, props.schema, props.table, columns]);

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
  catalog,
  schema,
  selectMode,
  isSelected,
  onToggleSelect,
  onRequestDdlMigration,
  onRequestDdlMigrationCustom,
  onRequestDataCopy,
  onRequestSchemaBatch,
  onRequestPreview,
}: { catalog: string; schema: string } & TreeProps) {
  const [open, setOpen] = useState(false);
  const [tables, setTables] = useState<StarburstTable[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || tables !== null) return;
    explorerApi
      .starburstTables(catalog, schema)
      .then(setTables)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, catalog, schema, tables]);

  const refresh = () => { setTables(null); setError(null); };
  // G20 — right-click offers the same real actions this row's own buttons do.
  // onRequestSchemaBatch takes TWO args here (catalog, schema) — Starburst
  // schemas are catalog-qualified, unlike Redshift's.
  const schemaMenuItems: ContextMenuItem[] = [{ label: "Refresh", onSelect: refresh }];
  if (onRequestSchemaBatch) {
    schemaMenuItems.push({
      label: "Batch migrate schema",
      onSelect: () => onRequestSchemaBatch(catalog, schema),
    });
  }
  const { onContextMenu, menuElement } = useNodeMenu(schemaMenuItems);

  return (
    <div className="tree-node">
      <div className="tree-toggle-row" onContextMenu={onContextMenu}>
        <button className="tree-toggle" onClick={() => setOpen((o) => !o)}>
          <span className={`tree-caret ${open ? "open" : ""}`}>
            <Icon name="chevron" size={12} />
          </span>{" "}
          {schema}
        </button>
        <RefreshControl label={`schema ${catalog}.${schema}`} onRefresh={refresh} />
        {menuElement}
        {onRequestSchemaBatch && (
          <button
            className="mini-btn batch-btn"
            onClick={() => onRequestSchemaBatch(catalog, schema)}
            title="Migrate every real table/view in this schema in one batch (distinct from single-object drag-and-drop)"
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
            const obj: DragObject = { system: "starburst", objectType: isView ? "view" : "table", catalog, schema, name: t.name };
            return (
              <TableRowWithColumns
                key={t.name}
                catalog={catalog}
                schema={schema}
                table={t.name}
                obj={obj}
                label={t.name}
                sub={isView ? "VIEW" : "TABLE"}
                glyph={isView ? "view" : "table"}
                selectMode={selectMode}
                selected={isSelected?.(obj)}
                onToggleSelect={onToggleSelect}
                onRequestDdlMigration={onRequestDdlMigration}
                onRequestDdlMigrationCustom={onRequestDdlMigrationCustom}
                onRequestDataCopy={onRequestDataCopy}
                onRequestPreview={onRequestPreview}
                isTable={!isView}
                canPreview
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function CatalogNode({
  catalog,
  selectMode,
  isSelected,
  onToggleSelect,
  onRequestDdlMigration,
  onRequestDdlMigrationCustom,
  onRequestDataCopy,
  onRequestSchemaBatch,
  onRequestPreview,
}: { catalog: string } & TreeProps) {
  const [open, setOpen] = useState(false);
  const [schemas, setSchemas] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || schemas !== null) return;
    explorerApi
      .starburstSchemas(catalog)
      .then((s) => setSchemas(s.map((x) => x.name)))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, catalog, schemas]);

  const refresh = () => { setSchemas(null); setError(null); };
  const { onContextMenu, menuElement } = useRefreshMenu(refresh);

  return (
    <div className="tree-node">
      <div className="tree-toggle-row" onContextMenu={onContextMenu}>
        <button className="tree-toggle" onClick={() => setOpen((o) => !o)}>
          <span className={`tree-caret ${open ? "open" : ""}`}>
            <Icon name="chevron" size={12} />
          </span>{" "}
          {catalog}
        </button>
        <RefreshControl label={`catalog ${catalog}`} onRefresh={refresh} />
        {menuElement}
      </div>
      {open && (
        <div className="tree-children">
          {error && <p className="error">{error}</p>}
          {schemas === null && !error && <p className="empty">Loading…</p>}
          {schemas?.map((s) => (
            <SchemaNode
              key={s}
              catalog={catalog}
              schema={s}
              selectMode={selectMode}
              isSelected={isSelected}
              onToggleSelect={onToggleSelect}
              onRequestDdlMigration={onRequestDdlMigration}
              onRequestDdlMigrationCustom={onRequestDdlMigrationCustom}
              onRequestDataCopy={onRequestDataCopy}
              onRequestSchemaBatch={onRequestSchemaBatch}
              onRequestPreview={onRequestPreview}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function StarburstTree({
  selectMode,
  isSelected,
  onToggleSelect,
  onRequestDdlMigration,
  onRequestDdlMigrationCustom,
  onRequestDataCopy,
  onRequestSchemaBatch,
}: TreeProps) {
  const [catalogs, setCatalogs] = useState<string[] | null>(null);
  const [udfs, setUdfs] = useState<StarburstUdf[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [udfOpen, setUdfOpen] = useState(false);
  // G19 — preview and UDF source both open in the centre-pane <PreviewPane>
  // now; this tree holds no view state of its own. (G18 note kept because it
  // still matters: Starburst UDF bodies ARE retrievable via SHOW CREATE
  // FUNCTION — an earlier "unavailable" panel was based on a wrong assumption.)
  const { openPreview } = usePreview();

  useEffect(() => {
    if (catalogs !== null) return;
    explorerApi
      .starburstCatalogs()
      .then((c) => setCatalogs(c.map((x) => x.name)))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [catalogs]);

  useEffect(() => {
    if (!udfOpen || udfs !== null) return;
    explorerApi.starburstUdfs().then(setUdfs).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [udfOpen, udfs]);

  const refreshCatalogs = () => { setCatalogs(null); setError(null); };
  const { onContextMenu: onRootContextMenu, menuElement: rootMenuElement } = useRefreshMenu(refreshCatalogs);

  // G20 — the UDF group node had no refresh icon and no context menu at all,
  // and refreshCatalogs above deliberately does NOT clear `udfs`, so Starburst
  // UDFs were un-refreshable for the whole session. Setting udfs back to null
  // re-fires the fetch effect above (its guard is `!udfOpen || udfs !== null`,
  // so a null value while the node is open re-runs it).
  const refreshUdfs = () => { setUdfs(null); setError(null); };
  const { onContextMenu: onUdfContextMenu, menuElement: udfMenuElement } = useRefreshMenu(refreshUdfs);

  return (
    <div className="source-panel starburst-panel" onContextMenu={onRootContextMenu}>
      <h3>
        <span className="engine-dot lakebridge" /> Starburst{" "}
        {SHOW_EXPERIMENTAL_STARBURST && (
          <>
            <span className="engine-dot experimental" /> <span className="engine-tag experimental">llm-transpile (experimental)</span>
          </>
        )}
        <span className="engine-tag">custom-ddl (deterministic)</span>
        <RefreshControl label="Starburst root (catalogs)" onRefresh={refreshCatalogs} />
      </h3>
      {/* G20: outside the <h3> — index.css:162 hides that heading in the rail
          layout, which was swallowing the root's right-click menu. */}
      {rootMenuElement}
      {error && <p className="error">{error}</p>}
      {catalogs === null && !error && <p className="empty">Loading real catalogs…</p>}
      {catalogs?.map((c) => (
        <CatalogNode
          key={c}
          catalog={c}
          selectMode={selectMode}
          isSelected={isSelected}
          onToggleSelect={onToggleSelect}
          onRequestDdlMigration={onRequestDdlMigration}
          onRequestDdlMigrationCustom={onRequestDdlMigrationCustom}
          onRequestDataCopy={onRequestDataCopy}
          onRequestSchemaBatch={onRequestSchemaBatch}
          onRequestPreview={(catalog, schema, table) =>
            openPreview({ kind: "table", system: "starburst", catalog, schema, name: table })
          }
        />
      ))}

      <div className="tree-node">
        <div className="tree-toggle-row" onContextMenu={onUdfContextMenu}>
          <button className="tree-toggle" onClick={() => setUdfOpen((o) => !o)}>
            <span className={`tree-caret ${udfOpen ? "open" : ""}`}>
              <Icon name="chevron" size={12} />
            </span>{" "}
            UDFs (galaxy.functions)
          </button>
          <RefreshControl label="UDFs (galaxy.functions)" onRefresh={refreshUdfs} />
          {udfMenuElement}
        </div>
        {udfOpen && (
          <div className="tree-children">
            {udfs === null && <p className="empty">Loading…</p>}
            {udfs?.length === 0 && <p className="empty">(none)</p>}
            {udfs?.map((u) => (
              <DraggableRow
                key={u.name}
                obj={{ system: "starburst", objectType: "udf", catalog: "galaxy", schema: "functions", name: u.name }}
                label={u.name}
                sub={`${u.return_type}(${u.argument_types})`}
                // G19: this used to claim the body was unrecoverable because
                // "SHOW FUNCTIONS only exposes the signature". That is false —
                // SHOW CREATE FUNCTION returns the real body, which the eye
                // button now shows. What is true is that the *migrate* path
                // still rejects UDFs, so only that is claimed here.
                warnReason="Migrating a UDF hits a real backend 400 rejection — the DDL translators don't cover function bodies yet. The eye button still shows the real source (SHOW CREATE FUNCTION). Not selectable for batch (backend rejects non table/view Starburst batch items)."
                selectMode={false}
                glyph="udf"
                onRequestDdlMigration={onRequestDdlMigration}
                onRequestDdlMigrationCustom={onRequestDdlMigrationCustom}
                onRequestUdfSource={(name) =>
                  openPreview({
                    kind: "routine",
                    system: "starburst",
                    schema: "functions",
                    catalog: "galaxy",
                    name,
                    routineType: "FUNCTION",
                  })
                }
              />
            ))}
          </div>
        )}
      </div>

    </div>
  );
}
