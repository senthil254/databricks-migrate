import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { MigrationCard, type Job } from "./MigrationCard";
import { ConfirmDialog } from "./ConfirmDialog";
import { explorerApi, type Migration } from "./explorerApi";
import { batchApi, type BatchItem, type BatchSummary } from "./batchApi";
import { dragKey, type DragObject } from "./dragTypes";

// G17 — this state used to live inside Explorer.tsx, which meant the object
// trees had to live there too (they need these callbacks). The user asked for
// one persistent Data Explorer serving BOTH the Migrations and AI Command
// surfaces, so the trees moved up into the shell — and this state had to come
// with them.
//
// Side benefit: the trees are now mounted exactly once instead of twice
// (Explorer had its own pair, ChatDataExplorer had another), so switching
// sections no longer re-fetches or loses expansion state.

let counter = 0;
function newKey() {
  counter += 1;
  return `job-${Date.now()}-${counter}`;
}

export interface TrackedBatch {
  key: string;
  label: string;
  batch: BatchSummary;
}

function toBatchItem(obj: DragObject): BatchItem {
  return {
    source_system: obj.system,
    object_type: obj.objectType,
    schema_name: obj.schema,
    name: obj.name,
    ...(obj.catalog ? { catalog: obj.catalog } : {}),
  };
}

interface MigrationActionsValue {
  /** G19 — bumped whenever a migration reaches a terminal state. The Databricks
   *  tree watches it and re-reads the target schema, so a newly created table,
   *  view, function or procedure appears without the user having to know which
   *  node's refresh button to press, or how long to wait first. */
  targetVersion: number;
  jobs: Job[];
  batches: TrackedBatch[];
  selectMode: boolean;
  selectedCount: number;
  setSelectMode: (on: boolean) => void;
  isSelected: (obj: DragObject) => boolean;
  toggleSelect: (obj: DragObject) => void;
  submitSelectedBatch: () => void;
  requestDataCopy: (
    system: "redshift" | "starburst",
    schema: string,
    table: string,
    catalog?: string,
  ) => void;
  requestSchemaBatch: (schema: string, catalog?: string) => void;
  runDdlMigration: (obj: DragObject) => void;
  runDdlMigrationCustom: (obj: DragObject) => void;
  runCreateAndCopy: (obj: DragObject) => void;
  /** What a drop on the target zone does — table/view creates the real object
   *  AND copies data; routines stay DDL-only (they have no data). */
  handleDrop: (obj: DragObject) => void;
}

const Ctx = createContext<MigrationActionsValue | null>(null);

export function useMigrationActions(): MigrationActionsValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useMigrationActions must be used inside <MigrationActionsProvider>");
  return v;
}

export function MigrationActionsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  // See MigrationActionsValue.targetVersion.
  const [targetVersion, setTargetVersion] = useState(0);
  const bumpTargetVersion = useCallback(() => setTargetVersion((v) => v + 1), []);
  // Concise, visually-hidden status announcer. The visible lists re-render
  // their full DOM on every poll tick, so making those containers aria-live
  // would re-read the whole list on each status change.
  const [announcement, setAnnouncement] = useState("");
  const [dataCopyTarget, setDataCopyTarget] = useState<
    { system: "redshift" | "starburst"; schema: string; table: string; catalog?: string } | null
  >(null);
  const pollRefs = useRef<Set<string>>(new Set());

  const [batches, setBatches] = useState<TrackedBatch[]>([]);
  const [schemaBatchTarget, setSchemaBatchTarget] = useState<
    { schema: string; includeData: boolean; catalog?: string } | null
  >(null);
  const [selectMode, setSelectModeState] = useState(false);
  const [selected, setSelected] = useState<Map<string, DragObject>>(new Map());
  const batchPollRefs = useRef<Set<string>>(new Set());

  const patchBatch = useCallback((key: string, patch: Partial<BatchSummary>) => {
    setBatches((prev) => {
      const next = prev.map((b) => (b.key === key ? { ...b, batch: { ...b.batch, ...patch } } : b));
      const updated = next.find((b) => b.key === key);
      if (updated && patch.status) {
        const settled = updated.batch.completed_items + updated.batch.failed_items;
        setAnnouncement(
          `${updated.label}: ${patch.status.replace(/_/g, " ")}, ${settled} of ${updated.batch.total_items} settled.`,
        );
      }
      return next;
    });
  }, []);

  const pollBatch = useCallback(
    (key: string, batchId: string) => {
      if (batchPollRefs.current.has(key)) return;
      batchPollRefs.current.add(key);
      const tick = async () => {
        if (!batchPollRefs.current.has(key)) return;
        try {
          const b = await batchApi.getBatch(batchId);
          patchBatch(key, b);
          if (b.status === "completed" || b.status === "completed_with_errors") {
            batchPollRefs.current.delete(key);
            return;
          }
        } catch {
          // transient — keep polling, best-effort progress view
        }
        setTimeout(tick, 2500);
      };
      tick();
    },
    [patchBatch],
  );

  const trackBatch = useCallback(
    (label: string, batch: BatchSummary) => {
      const key = newKey();
      setBatches((prev) => [{ key, label, batch }, ...prev]);
      pollBatch(key, batch.id);
    },
    [pollBatch],
  );

  const patchJob = useCallback((key: string, patch: Partial<Job>) => {
    setJobs((prev) => {
      const next = prev.map((j) => (j.key === key ? { ...j, ...patch } : j));
      const updated = next.find((j) => j.key === key);
      if (updated) {
        const status = updated.clientError ? "rejected" : updated.migration?.status;
        if (status) setAnnouncement(`${updated.name} migration: ${status}.`);
      }
      return next;
    });
  }, []);

  // While a job hasn't settled, poll GET /migrations to find the real
  // backend-side record and surface its live status (queued/running before the
  // triggering POST itself resolves).
  const pollForPickup = useCallback(
    (key: string, matches: (m: Migration) => boolean) => {
      if (pollRefs.current.has(key)) return;
      pollRefs.current.add(key);
      const tick = async () => {
        if (!pollRefs.current.has(key)) return;
        try {
          const list = await explorerApi.listMigrations();
          const found = list.find(matches);
          if (found) {
            patchJob(key, { migration: found });
            if (found.status === "completed" || found.status === "failed") {
              pollRefs.current.delete(key);
              return;
            }
          }
        } catch {
          // transient — keep polling
        }
        setTimeout(tick, 2000);
      };
      tick();
    },
    [patchJob],
  );

  const stopPolling = useCallback((key: string) => {
    pollRefs.current.delete(key);
  }, []);

  // All four job runners share this shape: create a tracked Job, start polling
  // for the real backend record, then settle on the POST's own result.
  const startJob = useCallback(
    (
      obj: { system: "redshift" | "starburst"; objectType: string },
      objectName: string,
      action: Job["action"],
      call: () => Promise<Migration>,
    ) => {
      const key = newKey();
      const triggeredAt = new Date().toISOString();
      const job: Job = {
        key,
        system: obj.system,
        objectType: obj.objectType,
        name: objectName,
        action,
        triggeredAt,
        migration: null,
        clientError: null,
        settled: false,
      };
      setJobs((prev) => [job, ...prev]);
      pollForPickup(
        key,
        (m) => m.source_system === obj.system && m.object_name === objectName && (m.started_at ?? "") >= triggeredAt,
      );
      call()
        .then((mig) => {
          patchJob(key, { migration: mig, settled: true });
          stopPolling(key);
          // The target schema just changed — tell the Databricks tree.
          bumpTargetVersion();
        })
        .catch((e: Error) => {
          patchJob(key, { clientError: e.message, settled: true });
          stopPolling(key);
        });
    },
    [patchJob, pollForPickup, stopPolling, bumpTargetVersion],
  );

  const qualifiedName = (obj: DragObject) =>
    obj.system === "redshift" ? `${obj.schema}.${obj.name}` : `${obj.catalog}.${obj.schema}.${obj.name}`;

  const runDdlMigration = useCallback(
    (obj: DragObject) => {
      startJob(obj, qualifiedName(obj), "ddl", () =>
        obj.system === "redshift"
          ? explorerApi.migrateRedshiftDdl(obj.objectType, obj.schema, obj.name)
          : explorerApi.migrateStarburstDdl(obj.objectType, obj.catalog ?? "", obj.schema, obj.name),
      );
    },
    [startJob],
  );

  // Deterministic Starburst DDL migration (fast, no LLM).
  const runDdlMigrationCustom = useCallback(
    (obj: DragObject) => {
      startJob(obj, qualifiedName(obj), "ddl-custom", () =>
        explorerApi.migrateStarburstDdlCustom(obj.objectType, obj.catalog ?? "", obj.schema, obj.name),
      );
    },
    [startJob],
  );

  // Creates the real destination object AND copies its data in one motion, no
  // confirm dialog — the drag gesture itself is the intent.
  const runCreateAndCopy = useCallback(
    (obj: DragObject) => {
      startJob(obj, qualifiedName(obj), "create-and-copy", () =>
        obj.system === "redshift"
          ? explorerApi.migrateRedshiftTableAndData(obj.schema, obj.name)
          : explorerApi.migrateStarburstTableAndData(obj.catalog ?? "", obj.schema, obj.name),
      );
    },
    [startJob],
  );

  const handleDrop = useCallback(
    (obj: DragObject) => {
      if (obj.objectType === "table" || obj.objectType === "view") {
        runCreateAndCopy(obj);
      } else if (obj.system === "starburst") {
        runDdlMigrationCustom(obj);
      } else {
        runDdlMigration(obj);
      }
    },
    [runCreateAndCopy, runDdlMigrationCustom, runDdlMigration],
  );

  const requestDataCopy = useCallback(
    (system: "redshift" | "starburst", schema: string, table: string, catalog?: string) => {
      setDataCopyTarget({ system, schema, table, catalog });
    },
    [],
  );

  function confirmDataCopy() {
    if (!dataCopyTarget) return;
    const { system, schema, table, catalog } = dataCopyTarget;
    setDataCopyTarget(null);
    const objectName = system === "redshift" ? `${schema}.${table}` : `${catalog}.${schema}.${table}`;
    startJob({ system, objectType: "table-data" }, objectName, "data", () =>
      system === "redshift"
        ? explorerApi.migrateRedshiftData(schema, table)
        : explorerApi.migrateStarburstData(catalog ?? "", schema, table),
    );
  }

  const requestSchemaBatch = useCallback((schema: string, catalog?: string) => {
    setSchemaBatchTarget({ schema, includeData: true, catalog });
  }, []);

  function confirmSchemaBatch() {
    if (!schemaBatchTarget) return;
    const { schema, includeData, catalog } = schemaBatchTarget;
    setSchemaBatchTarget(null);
    const system: "redshift" | "starburst" = catalog ? "starburst" : "redshift";
    const label = catalog ? `Starburst schema batch: ${catalog}.${schema}` : `Redshift schema batch: ${schema}`;
    const call = catalog
      ? batchApi.migrateStarburstSchemaBatch(catalog, schema, includeData)
      : batchApi.migrateRedshiftSchemaBatch(schema, includeData);
    call
      .then((b) => trackBatch(label, b))
      .catch((e: Error) => {
        trackBatch(`${label} (failed to dispatch)`, {
          id: "n/a",
          status: "completed_with_errors",
          total_items: 0,
          completed_items: 0,
          failed_items: 1,
          dispatched_items: 0,
          created_at: null,
          started_at: null,
          ended_at: null,
          migrations: [
            {
              id: "n/a",
              source_system: system,
              object_type: "batch",
              object_name: schema,
              engine: "lakebridge-transpile",
              status: "failed",
              source_ddl: null,
              output_ddl: null,
              error: e.message,
              row_count: null,
              started_at: null,
              ended_at: null,
              target_catalog: null,
              target_schema: null,
              target_table: null,
            },
          ],
        });
      });
  }

  const toggleSelect = useCallback((obj: DragObject) => {
    setSelected((prev) => {
      const next = new Map(prev);
      const k = dragKey(obj);
      if (next.has(k)) next.delete(k);
      else next.set(k, obj);
      return next;
    });
  }, []);

  const isSelected = useCallback((obj: DragObject) => selected.has(dragKey(obj)), [selected]);

  const setSelectMode = useCallback((on: boolean) => {
    setSelectModeState(on);
    setSelected(new Map());
  }, []);

  const submitSelectedBatch = useCallback(() => {
    const items = Array.from(selected.values()).map(toBatchItem);
    if (items.length === 0) return;
    setSelected(new Map());
    batchApi
      .migrateBatch(items)
      .then((b) => trackBatch(`Explicit batch (${items.length} objects)`, b))
      .catch((e: Error) => window.alert(`Batch dispatch rejected by backend: ${e.message}`));
  }, [selected, trackBatch]);

  useEffect(() => {
    const jobPolls = pollRefs.current;
    const batchPolls = batchPollRefs.current;
    return () => {
      jobPolls.clear();
      batchPolls.clear();
    };
  }, []);

  const value: MigrationActionsValue = {
    targetVersion,
    jobs,
    batches,
    selectMode,
    selectedCount: selected.size,
    setSelectMode,
    isSelected,
    toggleSelect,
    submitSelectedBatch,
    requestDataCopy,
    requestSchemaBatch,
    runDdlMigration,
    runDdlMigrationCustom,
    runCreateAndCopy,
    handleDrop,
  };

  return (
    <Ctx.Provider value={value}>
      {children}

      {/* Dialogs live at the provider level so they still work no matter which
          section is on screen when a tree action is triggered. */}
      {dataCopyTarget && (
        <ConfirmDialog
          titleId="data-copy-dialog-title"
          title="Copy real row data?"
          onCancel={() => setDataCopyTarget(null)}
          onConfirm={confirmDataCopy}
          confirmLabel="Copy data now"
        >
          {dataCopyTarget.system === "redshift" ? (
            <p>
              This reads every row from Redshift{" "}
              <span className="mono">
                {dataCopyTarget.schema}.{dataCopyTarget.table}
              </span>{" "}
              and writes it into a real Databricks table via a direct connector — separate from DDL migration
              and not a Lakebridge command.
            </p>
          ) : (
            <p>
              This reads every row from Starburst{" "}
              <span className="mono">
                {dataCopyTarget.catalog}.{dataCopyTarget.schema}.{dataCopyTarget.table}
              </span>{" "}
              and writes it into a real Databricks table via a direct connector — separate from DDL migration
              and not a Lakebridge command.
            </p>
          )}
        </ConfirmDialog>
      )}

      {schemaBatchTarget && (
        <ConfirmDialog
          titleId="schema-batch-dialog-title"
          title={
            schemaBatchTarget.catalog
              ? `Batch migrate real schema "${schemaBatchTarget.catalog}.${schemaBatchTarget.schema}"?`
              : `Batch migrate real schema "${schemaBatchTarget.schema}"?`
          }
          onCancel={() => setSchemaBatchTarget(null)}
          onConfirm={confirmSchemaBatch}
          confirmLabel="Start batch now"
        >
          {schemaBatchTarget.catalog ? (
            <p>
              This enumerates every real table/view currently in Starburst schema{" "}
              <span className="mono">
                {schemaBatchTarget.catalog}.{schemaBatchTarget.schema}
              </span>{" "}
              and migrates each one's DDL via the real fast Starburst engine (not the LLM path). A full schema
              can take a while for real.
            </p>
          ) : (
            <p>
              This enumerates every real table/view/function/procedure currently in Redshift schema{" "}
              <span className="mono">{schemaBatchTarget.schema}</span> and migrates each one's DDL via the real{" "}
              <span className="mono">POST /migrate/redshift/schema/{schemaBatchTarget.schema}/batch</span>{" "}
              endpoint. A full schema can take ~2 minutes for real.
            </p>
          )}
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={schemaBatchTarget.includeData}
              onChange={(e) => setSchemaBatchTarget({ ...schemaBatchTarget, includeData: e.target.checked })}
            />
            Also copy real row data for every base table (heavier — reads every row of every table, not just DDL)
          </label>
        </ConfirmDialog>
      )}

      {/* Real assistive-tech-visible status announcer. Visually hidden (not
          display:none, which screen readers also skip). */}
      <div aria-live="polite" role="status" className="visually-hidden">
        {announcement}
      </div>
    </Ctx.Provider>
  );
}

/** Re-exported so the Migrations section can render job cards from context. */
export { MigrationCard };
