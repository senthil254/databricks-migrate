// G8 — read-only Databricks (target) browse tree + data preview.
// Mirrors StarburstTree.tsx's catalog -> schema -> table expand/collapse
// shape and its "fetch once, cache in state" per-node pattern, but this
// tree is intentionally read-only: the data already lives in Databricks
// (it's the migration target, not a source), so there are no
// migrate/copy buttons here — only preview/columns/source views.
//
// G17 — brought to parity with RedshiftTree/StarburstTree: lazy column
// expansion, a per-schema function list, and a real function-source view.
// All three back onto real, verified routes (see explorerApi.databricks*);
// nothing here is stubbed. Text glyphs (▸ ▤ ◫ 👁) replaced with <Icon>.

import { useEffect, useRef, useState } from "react";
import {
  explorerApi,
  type Column,
  type DatabricksRoutine,
  type StarburstTable,
} from "./explorerApi";
import { Icon } from "./Icon";
import { usePreview } from "./PreviewPane";
import { useRefreshMenu } from "./ContextMenu";
import { useMigrationActions } from "./MigrationActions";

// Matches RedshiftTree.tsx's TypeGlyph — same class names, so the three
// trees pick up identical styling; only the glyph source differs (Icon.tsx
// rather than a literal character).
function TypeGlyph({ kind }: { kind: "table" | "view" | "routine" }) {
  const icon = kind === "table" ? "table" : kind === "view" ? "view" : "function";
  return (
    <span className={`type-glyph type-glyph-${kind}`} aria-hidden="true">
      <Icon name={icon} size={13} />
    </span>
  );
}

// G19 — this tree had no refresh affordance at any level, while Redshift and
// Starburst had one at every level. Same component and contract as theirs:
// clear the cached children so the existing fetch effect re-fires for that node
// only, plus the right-click menu binding.
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

function Caret({ open }: { open: boolean }) {
  return (
    <span className={`tree-caret ${open ? "open" : ""}`} aria-hidden="true">
      <Icon name="chevron" size={12} />
    </span>
  );
}

// Identical to RedshiftTree.tsx / StarburstTree.tsx's ColumnsList (same
// class names, same null-means-loading contract).
function ColumnsList({ columns }: { columns: Column[] | null }) {
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

// Lazy column expansion, mirroring RedshiftTree.tsx's TableRowWithColumns:
// same state shape (`open` + `columns`, fetch once on first expand, cache in
// state), same wrapper/class names.
function TableRowWithColumns({
  t,
  onPreview,
}: {
  t: StarburstTable;
  onPreview: (catalog: string, schema: string, name: string) => void;
}) {
  const isView = t.type === "view";
  const [open, setOpen] = useState(false);
  const [columns, setColumns] = useState<Column[] | null>(null);

  useEffect(() => {
    if (!open || columns !== null) return;
    explorerApi
      .databricksColumns(t.catalog, t.schema, t.name)
      .then(setColumns)
      .catch(() => setColumns([]));
  }, [open, t.catalog, t.schema, t.name, columns]);

  return (
    <div className="table-row-with-columns">
      <div className="tree-leaf-row">
        <div
          className="tree-leaf"
          data-tip={`${t.catalog}.${t.schema}.${t.name} · ${t.type}`}
          onClick={() => onPreview(t.catalog, t.schema, t.name)}
        >
          <button
            className="tree-caret-btn"
            onClick={(e) => {
              e.stopPropagation();
              setOpen((o) => !o);
            }}
            title="Show/hide columns"
            aria-label={`Toggle columns for ${t.name}`}
          >
            <Caret open={open} />
          </button>
          <TypeGlyph kind={isView ? "view" : "table"} />
          <span className="tree-leaf-label">{t.name}</span>
          <span className="tree-leaf-sub">{isView ? "VIEW" : "TABLE"}</span>
        </div>
        <button
          className="mini-btn"
          onClick={() => onPreview(t.catalog, t.schema, t.name)}
          title={`Preview real rows in ${t.name}`}
          aria-label={`Preview ${t.name}`}
        >
          <Icon name="eye" size={14} />
        </button>
      </div>
      {open && <ColumnsList columns={columns} />}
    </div>
  );
}

// G17 — UC functions, the Databricks-side counterpart of RedshiftTree's
// routines. The eye button loads the real source via the dedicated GET
// route; it never triggers a migration.
function FunctionRow({
  fn,
  onRequestSource,
}: {
  fn: DatabricksRoutine;
  onRequestSource: (catalog: string, schema: string, name: string) => void;
}) {
  return (
    <div className="tree-leaf-row">
      <div
        className="tree-leaf"
        data-tip={`${fn.catalog}.${fn.schema}.${fn.name} · ${fn.type}`}
        onClick={() => onRequestSource(fn.catalog, fn.schema, fn.name)}
      >
        <TypeGlyph kind="routine" />
        <span className="tree-leaf-label">{fn.name}</span>
        <span className="tree-leaf-sub">{fn.type}</span>
      </div>
      <button
        className="mini-btn"
        onClick={() => onRequestSource(fn.catalog, fn.schema, fn.name)}
        title={`View real source for ${fn.catalog}.${fn.schema}.${fn.name}`}
        aria-label={`View source ${fn.name}`}
      >
        <Icon name="eye" size={14} />
      </button>
    </div>
  );
}

function SchemaNode({
  catalog,
  schema,
  onPreview,
  onRequestSource,
}: {
  catalog: string;
  schema: string;
  onPreview: (catalog: string, schema: string, name: string) => void;
  onRequestSource: (catalog: string, schema: string, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tables, setTables] = useState<StarburstTable[] | null>(null);
  const [functions, setFunctions] = useState<DatabricksRoutine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // G19 — auto-refresh after a migration lands. Clearing the cached children
  // makes the fetch effect below re-fire, exactly as the manual refresh button
  // does. Only for an expanded node: refetching collapsed nodes would hammer
  // the warehouse for lists nobody is looking at.
  const { targetVersion } = useMigrationActions();
  const seenVersion = useRef(targetVersion);
  useEffect(() => {
    if (seenVersion.current === targetVersion) return;
    seenVersion.current = targetVersion;
    if (!open) return;
    setTables(null);
    setFunctions(null);
  }, [targetVersion, open]);

  useEffect(() => {
    if (!open || tables !== null) return;
    Promise.all([explorerApi.databricksTables(catalog, schema), explorerApi.databricksFunctions(catalog, schema)])
      .then(([t, f]) => {
        setTables(t);
        setFunctions(f);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, catalog, schema, tables]);

  const refresh = () => {
    setTables(null);
    setFunctions(null);
    setError(null);
  };
  const { onContextMenu, menuElement } = useRefreshMenu(refresh);

  return (
    <div className="tree-node">
      <div className="tree-toggle-row" onContextMenu={onContextMenu}>
        <button className="tree-toggle" onClick={() => setOpen((o) => !o)}>
          <Caret open={open} /> {schema}
        </button>
        <RefreshControl label={`schema ${catalog}.${schema}`} onRefresh={refresh} />
        {menuElement}
      </div>
      {open && (
        <div className="tree-children">
          {error && <p className="error">{error}</p>}
          {tables === null && !error && <p className="empty">Loading…</p>}
          {tables?.length === 0 && functions?.length === 0 && <p className="empty">(no tables or functions)</p>}
          {tables?.map((t) => (
            <TableRowWithColumns key={t.name} t={t} onPreview={onPreview} />
          ))}
          {functions?.map((f) => (
            <FunctionRow key={f.name} fn={f} onRequestSource={onRequestSource} />
          ))}
        </div>
      )}
    </div>
  );
}

function CatalogNode({
  catalog,
  onPreview,
  onRequestSource,
}: {
  catalog: string;
  onPreview: (catalog: string, schema: string, name: string) => void;
  onRequestSource: (catalog: string, schema: string, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [schemas, setSchemas] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || schemas !== null) return;
    explorerApi
      .databricksSchemas(catalog)
      .then((s) => setSchemas(s.map((x) => x.name)))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, catalog, schemas]);

  const refresh = () => {
    setSchemas(null);
    setError(null);
  };
  const { onContextMenu, menuElement } = useRefreshMenu(refresh);

  return (
    <div className="tree-node">
      <div className="tree-toggle-row" onContextMenu={onContextMenu}>
        <button className="tree-toggle" onClick={() => setOpen((o) => !o)}>
          <Caret open={open} /> {catalog}
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
              onPreview={onPreview}
              onRequestSource={onRequestSource}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function DatabricksTree() {
  const [catalogs, setCatalogs] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // G19 — preview and function source both open in the centre-pane
  // <PreviewPane>; this tree keeps no view state of its own.
  const { openPreview } = usePreview();

  // G19: guarded on `catalogs === null` (was `[]` deps, fetch-once) so the new
  // root refresh can re-trigger it by clearing state, same as the other trees.
  useEffect(() => {
    if (catalogs !== null) return;
    explorerApi
      .databricksCatalogs()
      .then((c) => setCatalogs(c.map((x) => x.name)))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [catalogs]);

  const refreshRoot = () => {
    setCatalogs(null);
    setError(null);
  };
  const { onContextMenu: onRootContextMenu, menuElement: rootMenuElement } = useRefreshMenu(refreshRoot);

  return (
    <div className="source-panel databricks-panel" onContextMenu={onRootContextMenu}>
      <h3>
        <span className="engine-dot" /> Databricks (target — read-only)
        <RefreshControl label="Databricks root (catalogs)" onRefresh={refreshRoot} />
        {rootMenuElement}
      </h3>
      {error && <p className="error">{error}</p>}
      {catalogs === null && !error && <p className="empty">Loading real catalogs…</p>}
      {catalogs?.map((c) => (
        <CatalogNode
          key={c}
          catalog={c}
          onPreview={(catalog, schema, table) =>
            openPreview({ kind: "table", system: "databricks", catalog, schema, name: table })
          }
          onRequestSource={(catalog, schema, name) =>
            openPreview({ kind: "routine", system: "databricks", catalog, schema, name, routineType: "FUNCTION" })
          }
        />
      ))}
    </div>
  );
}
