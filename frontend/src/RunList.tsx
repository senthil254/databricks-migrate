import type { Run } from "./api";
import { STATUS_META, dispatchCaveat } from "./statusMeta";

interface Props {
  runs: Run[];
  onSelect: (id: string) => void;
}

export function RunList({ runs, onSelect }: Props) {
  if (runs.length === 0) {
    return <p className="empty">No runs yet — trigger one above.</p>;
  }

  return (
    <table className="run-table">
      <thead>
        <tr>
          <th>Run</th>
          <th>Command</th>
          <th>Status</th>
          <th>Started</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const meta = STATUS_META[r.status];
          const caveat = r.status === "completed" ? dispatchCaveat(r.command) : null;
          return (
            <tr key={r.id} onClick={() => onSelect(r.id)} className="run-row">
              <td className="mono">{r.id}</td>
              <td className="mono">{r.command}</td>
              <td>
                <span className={`status-pill ${meta.className}`}>
                  <span aria-hidden="true">{meta.icon}</span> {meta.label}
                </span>
                {caveat && <span className="caveat" title={caveat}>⚠ dispatched only</span>}
              </td>
              <td className="mono">{r.started_at ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
