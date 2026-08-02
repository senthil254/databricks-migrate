import { TargetDropZone } from "./TargetDropZone";
import { MigrationCard } from "./MigrationCard";
import { BatchCard } from "./BatchCard";
import { PipelineFlow } from "./PipelineFlow";
import { useMigrationActions } from "./MigrationActions";
import { useSpotlight } from "./useSpotlight";
import { Icon } from "./Icon";

// G17 — the Migrations surface. The object trees and all the job/batch state
// that used to live here moved to <DataExplorerPanel> and <MigrationActions>
// respectively, so this file is now just the target side of the drag plus the
// result lists.

function ActivePipeline() {
  const { jobs } = useMigrationActions();
  const { spotlightProps } = useSpotlight();
  const latest = jobs[0];

  const verdict = !latest
    ? null
    : latest.clientError || latest.migration?.status === "failed"
      ? { state: "failed" as const, label: "Failed" }
      : latest.migration?.status === "completed"
        ? { state: "ok" as const, label: "Verified" }
        : { state: "running" as const, label: "Running" };

  return (
    <section className="card card-spotlight pipeline-hero" {...spotlightProps}>
      <header className="pipeline-hero-head">
        <div>
          <span className="eyebrow">Active pipeline</span>
          <h2 className="pipeline-hero-title">
            {latest ? latest.name : "Redshift / Starburst"} <Icon name="arrow-right" size={16} /> Databricks
          </h2>
        </div>
        {verdict && (
          <span className={`pill state-${verdict.state} ${verdict.state === "running" ? "pill-live" : ""}`}>
            <span className="pill-dot" />
            {verdict.label}
          </span>
        )}
      </header>

      {latest ? (
        <PipelineFlow job={latest} variant="hero" />
      ) : (
        <p className="pipeline-hero-idle">
          No migration yet this session. Drag a real object from the data explorer onto the target zone below.
        </p>
      )}
    </section>
  );
}

export function Explorer() {
  const { batches, jobs, selectMode, selectedCount, setSelectMode, submitSelectedBatch, handleDrop } =
    useMigrationActions();
  // G19 — the data explorer moved out of this page and into the left rail
  // (App.tsx) as a nav item under "Migrations". This page is now purely the
  // target side of the drag plus the result lists.

  return (
    <div className="explorer">
      <div className="explorer-work">
      <ActivePipeline />

      <div className="explorer-grid">
        <TargetDropZone onDropObject={handleDrop} />

        <div className="batch-toolbar card">
          <div className="batch-toolbar-head">
            <span className="eyebrow">Batch</span>
            <p className="muted">Migrate many real objects in one dispatch instead of dragging each.</p>
          </div>
          <button className={selectMode ? "active" : ""} onClick={() => setSelectMode(!selectMode)}>
            <Icon name="catalog" size={15} />
            {selectMode ? "Exit batch-select mode" : "Select multiple objects"}
          </button>
          {selectMode && (
            <>
              <span className="muted">{selectedCount} selected</span>
              <button className="primary" disabled={selectedCount === 0} onClick={submitSelectedBatch}>
                <Icon name="migrate" size={15} />
                Migrate selected as batch
              </button>
            </>
          )}
        </div>
      </div>

      <h2 className="section-title">Batches (this session)</h2>
      {batches.length === 0 && (
        <p className="empty">
          Use "batch migrate schema" on a schema in the data explorer, or select multiple objects, to start a
          real batch.
        </p>
      )}
      <div className="migration-list">
        {batches.map((b) => (
          <BatchCard key={b.key} label={b.label} batch={b.batch} />
        ))}
      </div>

      <h2 className="section-title">Migrations (this session)</h2>
      {jobs.length === 0 && (
        <p className="empty">
          Drag an object from the data explorer, use its "migrate" button (keyboard-operable alternative to
          drag), or use "copy data" on a table.
        </p>
      )}
      <div className="migration-list">
        {jobs.map((j, i) => (
          // i === 0 is the job the ActivePipeline hero above is already
          // showing — suppress its duplicate in-card pipeline (G19).
          <MigrationCard key={j.key} job={j} showPipeline={i !== 0} />
        ))}
      </div>
      </div>
    </div>
  );
}
