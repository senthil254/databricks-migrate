import { useEffect, useState, useCallback } from "react";
import { historyApi, type HistoryItem, type HistoryKind } from "./historyApi";
import { ViewDataAction } from "./MigrationCard";
import type { Migration } from "./explorerApi";
import { ReconcileView } from "./ReconcileView";
import { Icon } from "./Icon";

const POLL_MS = 4000;

const KIND_LABEL: Record<HistoryKind, string> = {
  run: "Run",
  migration: "Migration",
  batch: "Batch",
};

// Reuses the same engine-dot palette already established in
// MigrationCard.tsx/BatchCard.tsx (green = lakebridge/deterministic-ish,
// amber = experimental/in-progress, blue = data, red = error) rather than
// inventing new colors, per the G4 task's explicit instruction.
const KIND_DOT: Record<HistoryKind, string> = {
  run: "lakebridge",
  migration: "experimental",
  batch: "data",
};

interface Props {
  onOpenRun: (runId: string) => void;
}

export function HistoryList({ onOpenRun }: Props) {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [filter, setFilter] = useState<"all" | HistoryKind>("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    historyApi
      .list()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const filtered = filter === "all" ? items : items.filter((i) => i.kind === filter);
  const counts: Record<"all" | HistoryKind, number> = {
    all: items.length,
    run: items.filter((i) => i.kind === "run").length,
    migration: items.filter((i) => i.kind === "migration").length,
    batch: items.filter((i) => i.kind === "batch").length,
  };

  return (
    <div className="history-view">
      <p className="sub-note muted">
        Real unified read of every run/migration/batch this backend has ever recorded — from{" "}
        <span className="mono">GET /history</span>, {items.length} real items, newest first.
      </p>

      {error && <p className="error">{error}</p>}

      {/* G18: these filters used to reuse `.batch-toolbar`, whose G17 redefinition
          (flex-direction: column) is meant for the Migrations batch card and made
          this row stack vertically. They are a different component with different
          intent, so they now own `.history-filters` instead of fighting that rule. */}
      {/* role="group" with aria-pressed toggles, not a tablist: these filter a
          list in place, they do not switch tab panels. tablist children must
          be role="tab" + aria-selected, which would be the wrong semantics. */}
      <div className="history-filters" role="group" aria-label="Filter history by kind">
        {(["all", "run", "migration", "batch"] as const).map((k) => (
          <button
            key={k}
            className={`history-filter${filter === k ? " active" : ""}`}
            onClick={() => setFilter(k)}
            aria-pressed={filter === k}
          >
            <span className="history-filter-count">{counts[k]}</span>
            <span className="history-filter-label">{k === "all" ? "All" : KIND_LABEL[k]}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 && <p className="empty">No {filter === "all" ? "" : filter} items yet.</p>}

      <div className="history-list">
        {filtered.map((item) => {
          const key = `${item.kind}:${item.id}`;
          const isOpen = expanded === key;
          return (
            <div key={key} className={`history-row history-kind-${item.kind}`}>
              <button
                className="history-row-summary"
                onClick={() => setExpanded(isOpen ? null : key)}
                aria-expanded={isOpen}
              >
                <span className={`engine-dot ${KIND_DOT[item.kind]}`} />
                <span className={`kind-tag kind-tag-${item.kind}`}>{KIND_LABEL[item.kind]}</span>
                <span className="mono">{item.id}</span>
                <span className="history-row-desc">{describe(item)}</span>
                <span className={`status-pill status-${normalizeStatus(item.status)}`}>{item.status}</span>
                <span className="muted mono history-row-time">{item.sort_key ?? "—"}</span>
                <span className={`tree-caret ${isOpen ? "open" : ""}`} aria-hidden="true"><Icon name="chevron" size={12} /></span>
              </button>

              {isOpen && (
                <div className="history-row-detail">
                  {item.kind === "run" && (
                    <RunHistoryDetail runId={item.id} command={item.command} onOpenRun={onOpenRun} />
                  )}
                  {item.kind === "migration" && (
                    <div className="history-detail-block">
                      <p className="muted">
                        {item.source_system} · {item.object_type} · engine: {item.engine}
                      </p>
                      {item.error && (
                        <div className="callout-warn">
                          <strong>Error:</strong>
                          <pre className="mono">{item.error}</pre>
                        </div>
                      )}
                      {item.source_ddl && (
                        <details>
                          <summary>Source DDL</summary>
                          <pre className="mono code-block">{item.source_ddl}</pre>
                        </details>
                      )}
                      {item.output_ddl && (
                        <details open>
                          <summary>Output</summary>
                          <pre className="mono code-block">{item.output_ddl}</pre>
                        </details>
                      )}
                      {item.row_count !== null && <p className="muted">rows copied: {item.row_count}</p>}
                      {/* G8: reuse the exact ViewDataAction the Explorer's session-local
                          migration list uses, so History (the persistent, cross-session
                          view most users actually browse for "did this land in
                          Databricks?") gets the same real-data preview, not a second
                          divergent implementation. */}
                      {item.status === "completed" &&
                        item.target_catalog &&
                        item.target_schema &&
                        item.target_table && (
                          <ViewDataAction migration={item as unknown as Migration} />
                        )}
                    </div>
                  )}
                  {item.kind === "batch" && (
                    <div className="history-detail-block">
                      <p className="muted">
                        {item.completed_items} completed / {item.failed_items} failed / {item.total_items} total
                        {item.dispatched_items < item.total_items && ` (${item.dispatched_items} dispatched)`}
                      </p>
                      <p className="muted mono">
                        created {item.created_at} · started {item.started_at ?? "—"} · ended {item.ended_at ?? "—"}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function describe(item: HistoryItem): string {
  if (item.kind === "run") return item.command;
  if (item.kind === "migration") return `${item.object_name} (${item.source_system})`;
  return `${item.total_items} objects`;
}

// history items reuse Run/Migration/Batch statuses, which overlap
// ("running"/"completed"/"failed"/"queued"/"pending") but aren't 100%
// identical (batches also use "pending"/"completed_with_errors") — map the
// ones outside the base STATUS_META vocabulary to the closest existing
// status-pill class rather than inventing a parallel set of colors.
function normalizeStatus(status: string): string {
  if (status === "pending") return "queued";
  if (status === "completed_with_errors") return "failed";
  return status;
}

function RunHistoryDetail({
  runId,
  command,
  onOpenRun,
}: {
  runId: string;
  command: string;
  onOpenRun: (runId: string) => void;
}) {
  return (
    <div className="history-detail-block">
      <button className="mini-btn" onClick={() => onOpenRun(runId)}>
        Open full run (events log) in Sample runs →
      </button>
      {command === "reconcile" && <ReconcileView runId={runId} />}
    </div>
  );
}
