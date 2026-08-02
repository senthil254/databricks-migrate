import { useEffect, useState } from "react";
import { api, type Run, type RunEvent } from "./api";
import { STATUS_META, dispatchCaveat } from "./statusMeta";
import { ReconcileView } from "./ReconcileView";

interface Props {
  runId: string;
  onBack: () => void;
}

const POLL_MS = 1500;

export function RunDetail({ runId, onBack }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const [r, ev] = await Promise.all([api.getRun(runId), api.getEvents(runId)]);
        if (stopped) return;
        setRun(r);
        setEvents(ev);
        setError(null);
        // keep polling while not in a terminal state
        if (r.status === "queued" || r.status === "running") {
          timer = setTimeout(tick, POLL_MS);
        }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : String(e));
      }
    }

    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId]);

  if (error) return <p className="error">Failed to load run: {error}</p>;
  if (!run) return <p>Loading…</p>;

  const meta = STATUS_META[run.status];
  const caveat = run.status === "completed" ? dispatchCaveat(run.command) : null;

  return (
    <div className="run-detail">
      <button onClick={onBack} className="back-btn">← Back to runs</button>
      <h2 className="mono">{run.id} — {run.command}</h2>

      <div className="run-meta">
        <span className={`status-pill ${meta.className}`}>
          <span aria-hidden="true">{meta.icon}</span> {meta.label}
        </span>
        {run.exit_code !== null && <span className="mono">exit {run.exit_code}</span>}
      </div>

      {caveat && (
        <div className="callout-warn">
          <strong>Note:</strong> {caveat}
        </div>
      )}

      <h3>Events</h3>
      <div className="log-view">
        {events.length === 0 && <p className="empty">No events yet.</p>}
        {events.map((e) => (
          <div key={e.id} className={`log-line log-${e.type}`}>
            <span className="log-ts mono">{e.timestamp}</span>
            <span className="log-type mono">[{e.type}]</span>
            <span className="log-msg mono">{e.message}</span>
          </div>
        ))}
      </div>

      {run.command === "reconcile" && <ReconcileView runId={run.id} />}
    </div>
  );
}
