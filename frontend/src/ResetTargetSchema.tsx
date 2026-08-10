import { useState } from "react";
import { API_BASE as BASE } from "./apiBase";
import { ConfirmDialog } from "./ConfirmDialog";
import { Icon } from "./Icon";

// Rail item: reset the migration target schema back to its demo baseline.
//
// After a few test runs the target schema fills with migrated objects and you
// can no longer tell what the migration you just ran produced from what an
// earlier run left behind. This drops everything except one Redshift table, one
// Starburst table, and the MCP probe function, so the next migration is
// visibly new.
//
// Two deliberate safety properties:
//
//  * The whole item is behind SHOW_TESTING_TOOLS (VITE_TESTING_TOOLS=1), so it
//    is absent from the rail during a demo.
//  * Clicking it does NOT delete anything. It fetches what is there and shows
//    exactly which objects would be dropped and which kept; only the confirm
//    button in that dialog destroys anything. A destructive control should
//    never be a single blind click, even for the person who built it.

interface TargetObject {
  name: string;
  kind: string;
  keep: boolean;
}

interface TargetState {
  catalog: string;
  schema: string;
  objects: TargetObject[];
}

export function ResetTargetSchema() {
  const [state, setState] = useState<TargetState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const doomed = state ? state.objects.filter((o) => !o.keep) : [];
  const kept = state ? state.objects.filter((o) => o.keep) : [];

  async function openPreview() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch(`${BASE}/admin/target-objects`);
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? r.statusText);
      setState(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setState(null);
    setBusy(true);
    try {
      const r = await fetch(`${BASE}/admin/reset-target-schema`, { method: "POST" });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? r.statusText);
      const failed = (body.failed ?? []).length;
      setResult(
        `Dropped ${(body.dropped ?? []).length}, kept ${(body.kept ?? []).length}` +
          (failed ? ` — ${failed} failed` : ""),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        className="rail-item rail-testing"
        onClick={openPreview}
        disabled={busy}
        title="Reset the migration target schema to its demo baseline (destructive)"
      >
        <Icon name="refresh" size={17} />
        <span className="rail-label">{busy ? "working…" : "testing"}</span>
      </button>

      {(error || result) && (
        <p className={`rail-testing-msg ${error ? "err" : "ok"}`}>{error ?? result}</p>
      )}

      {state && (
        <ConfirmDialog
          titleId="reset-target-schema"
          title="Reset migration target schema?"
          confirmLabel={doomed.length ? `Drop ${doomed.length} object(s)` : "Nothing to drop"}
          onCancel={() => setState(null)}
          onConfirm={doomed.length ? reset : () => setState(null)}
        >
          <p>
            Drops <strong>{doomed.length}</strong> object(s) from{" "}
            <span className="mono">
              {state.catalog}.{state.schema}
            </span>
            , keeping <strong>{kept.length}</strong>.
          </p>

          <div className="reset-lists">
            <div>
              <span className="eyebrow">Keep</span>
              <ul className="reset-list">
                {kept.map((o) => (
                  <li key={o.name} className="mono keep">
                    {o.name} <span className="muted">{o.kind.toLowerCase()}</span>
                  </li>
                ))}
                {!kept.length && <li className="muted">none present</li>}
              </ul>
            </div>
            <div>
              <span className="eyebrow">Drop</span>
              <ul className="reset-list">
                {doomed.map((o) => (
                  <li key={o.name} className="mono drop">
                    {o.name} <span className="muted">{o.kind.toLowerCase()}</span>
                  </li>
                ))}
                {!doomed.length && <li className="muted">already at baseline</li>}
              </ul>
            </div>
          </div>

          <p className="muted">
            Real objects are dropped from Databricks. Each can be recreated by re-running its
            migration; nothing in Redshift or Starburst is touched.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
