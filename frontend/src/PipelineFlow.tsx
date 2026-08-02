import type { Job } from "./MigrationCard";
import { Icon, type IconName } from "./Icon";

// Horizontal 3-node pipeline-flow, modeled on the LAKEBRIDGE reference mockup
// (source cluster → transpiling → target zone). Purely presentational over the
// Job/Migration state MigrationActions already tracks — no new backend calls.
//
// Stage mapping is deliberately coarse: the backend gives one overall
// Migration.status per job, not a per-stage signal. We do not invent
// finer-grained progress than actually exists.
//   1. "Reading source"         — done once the job exists (dispatch implies
//      the backend read the source object).
//   2. "Creating + transpiling" — the DDL/create-object step.
//   3. "Writing target"         — the data-copy step. Only applies to "data"
//      and "create-and-copy" jobs; DDL-only jobs skip it (skipped, not failed).

type StageStatus = "not-started" | "in-progress" | "done" | "failed" | "skipped";

interface Stage {
  label: string;
  caption: string;
  icon: IconName;
  status: StageStatus;
}

const STATE_CLASS: Record<StageStatus, string> = {
  done: "state-ok",
  "in-progress": "state-running",
  failed: "state-failed",
  "not-started": "state-queued",
  skipped: "state-queued",
};

const STATUS_TEXT: Record<StageStatus, string> = {
  done: "done",
  "in-progress": "in progress",
  failed: "failed",
  "not-started": "pending",
  skipped: "skipped",
};

function computeStages(job: Job): Stage[] {
  // G19 fix: `job.settled` only flips when the *triggering POST* resolves. The
  // poller in MigrationActions can find the real backend record and report
  // status "completed" well before that — which rendered a card headed
  // COMPLETED whose stages all still read IN PROGRESS. Terminal state must come
  // from the migration's own status too, not from settled alone.
  const status = job.migration?.status;
  const settled = job.settled || status === "completed" || status === "failed";
  const failed = !!job.clientError || status === "failed";
  const hasDataStage = job.action === "data" || job.action === "create-and-copy";

  const sourceLabel = job.system === "redshift" ? "Redshift" : "Starburst";

  const reading: Stage = {
    label: sourceLabel,
    caption: "reading source",
    icon: "database",
    status: "done",
  };

  let creatingStatus: StageStatus;
  if (job.action === "data") {
    // Explicit "copy data" jobs skip object creation — the target already
    // exists by the time this job runs.
    creatingStatus = "skipped";
  } else if (!settled) {
    creatingStatus = "in-progress";
  } else {
    creatingStatus = failed ? "failed" : "done";
  }
  const creating: Stage = {
    label: "Transpiling",
    caption: job.action === "ddl-custom" ? "deterministic engine" : "Lakebridge",
    icon: "spark",
    status: creatingStatus,
  };

  // G19: this used to mark the target stage "skipped" for every DDL migration,
  // because a DDL migration only produced converted SQL. `migrate` now creates
  // the real object, so a procedure that was genuinely created in Databricks was
  // being labelled SKIPPED. Views are the one real exception — their body
  // references source tables that don't exist in the target, so they are
  // deliberately not executed.
  const writesTarget = hasDataStage || job.objectType !== "view";

  let writingStatus: StageStatus;
  if (!writesTarget) {
    writingStatus = "skipped";
  } else if (!settled) {
    writingStatus = creatingStatus === "failed" ? "not-started" : "in-progress";
  } else {
    writingStatus = failed ? "failed" : "done";
  }
  const writing: Stage = {
    label: "Databricks",
    caption: hasDataStage ? "writing target" : writesTarget ? "creating object" : "not applied",
    icon: "catalog",
    status: writingStatus,
  };

  return [reading, creating, writing];
}

export function PipelineFlow({ job, variant = "compact" }: { job: Job; variant?: "compact" | "hero" }) {
  const stages = computeStages(job);

  return (
    <div
      className={`pipeline-flow pipeline-flow-${variant}`}
      aria-label={`Pipeline status for ${job.name}`}
    >
      {stages.map((s, i) => (
        <div className="pipeline-node" key={s.label + i}>
          <div className={`pipeline-ring ${STATE_CLASS[s.status]} pipeline-${s.status}`}>
            <span className="pipeline-ring-inner">
              <Icon name={s.icon} size={variant === "hero" ? 22 : 16} />
            </span>
          </div>
          <span className="pipeline-node-label">{s.label}</span>
          <span className="pipeline-node-caption">{s.caption}</span>
          <span className={`pipeline-node-status ${STATE_CLASS[s.status]}`}>{STATUS_TEXT[s.status]}</span>

          {i < stages.length - 1 && (
            <span
              className={`pipeline-connector ${
                stages[i + 1].status === "done" || stages[i + 1].status === "in-progress" ? "lit" : ""
              }`}
              aria-hidden="true"
            />
          )}
        </div>
      ))}
    </div>
  );
}
