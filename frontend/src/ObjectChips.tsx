import { useEffect, useState } from "react";
import { explorerApi } from "./explorerApi";
import { Icon } from "./Icon";

// G16 Phase B — Google-search-suggestion-style chips near the chat input.
// Fetches a small, real object inventory directly via explorerApi (no new
// chat.py "list objects" intent — matches the plan's exploration finding
// that no such intent exists or is needed) and renders each as a clickable
// pill. Typing in the chat input filters chips client-side by substring
// match; nothing here talks to the backend on every keystroke.
//
// Deliberately scoped small: one representative schema per source system
// (first schema/catalog returned), capped at CHIP_LIMIT_PER_SYSTEM objects
// each, rather than enumerating every object in every catalog.
//
// IMPORTANT: clicking a chip must NOT migrate anything directly. It calls
// onPick(text) with a natural-language request; the caller (ChatPanel)
// feeds that through the exact same submitInstruction ->
// POST /chat/plan -> ConfirmDialog -> POST /chat/execute flow used for
// typed messages. No separate execute path lives in this file.

//
// G19 — routine chips now MIGRATE, like table chips, instead of only showing
// SQL. When they were added (G18) `migrate` produced converted SQL and created
// nothing, so "show the source" was the only honest thing a routine chip could
// do. `migrate` now applies the DDL to Databricks — verified live: Redshift
// functions and procedures both really get created — so a routine chip that
// only printed SQL would understate what the product can do.
//
// Starburst UDFs are the exception and still show source only: the backend
// rejects UDF migration with a real 400 (the DDL translators don't cover
// function bodies), so offering "migrate" there would promise a guaranteed
// failure.
//
// Honesty constraint baked in here: Starburst/Trino has no stored procedures
// at all (CREATE PROCEDURE is a grammar-level SYNTAX_ERROR), so a Starburst
// routine chip is only ever labelled "function". Only Redshift chips may say
// "procedure".

const CHIP_LIMIT_PER_SYSTEM = 8;
const ROUTINE_CHIP_LIMIT_PER_SYSTEM = 6;

// G19 — chips are pinned to the two schemas that migrate quickly and cleanly,
// rather than "whatever schema sorts first". Previously this took
// redshiftSchemas()[0] and starburstCatalogs()[0], which is why Starburst chips
// came from `federated_mysql` — a federated catalog that is slow and error-prone
// to migrate from. These are the demo schemas the user actually demos with.
const REDSHIFT_CHIP_SCHEMA = "demo_fast_test";
const STARBURST_CHIP_CATALOG = "mcp2ohio";
const STARBURST_CHIP_SCHEMA = "test_writes";

/** A relation chip is only worth offering if the object actually has rows —
 *  "migrate this and its data" on an empty table demos nothing. Checked with a
 *  1-row preview (the cheapest real proof) rather than assumed. */
async function hasRows(load: () => Promise<{ row_count: number }>): Promise<boolean> {
  try {
    const r = await load();
    return r.row_count > 0;
  } catch {
    // Unreadable is as good as unusable for a suggestion chip — a chip that
    // errors on click is worse than no chip.
    return false;
  }
}

// What a routine chip hands back to the caller. `schema` is only meaningful
// for Redshift; Starburst UDFs are global to galaxy.functions and the source
// route takes the bare name (verified: GET /explore/starburst/udfs/{name}/source).
export interface RoutineRef {
  system: "redshift" | "starburst";
  /** Redshift schema. Undefined for Starburst UDFs. */
  schema?: string;
  name: string;
  /** "PROCEDURE" | "FUNCTION" — never "PROCEDURE" for Starburst. */
  routineType: string;
  /** Human-readable "Redshift · public.sp_x" form, for the transcript header. */
  label: string;
}

interface TableChip {
  key: string;
  label: string;
  system: "redshift" | "starburst";
  kind: "table";
  message: string;
}

interface RoutineChip {
  key: string;
  label: string;
  system: "redshift" | "starburst";
  kind: "routine";
  ref: RoutineRef;
  /** Present when this routine can really be migrated (Redshift). Absent for
   *  Starburst UDFs, which the backend rejects — those show source only. */
  message?: string;
}

type Chip = TableChip | RoutineChip;

export function ObjectChips({
  filter,
  disabled,
  onPick,
  onShowSource,
}: {
  filter: string;
  disabled: boolean;
  onPick: (text: string) => void;
  onShowSource: (ref: RoutineRef) => void;
}) {
  const [chips, setChips] = useState<Chip[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Every chip is gated on a live "does this table actually have rows?" preview
  // against Redshift and Starburst — measured at ~2-2.5s each, so the strip
  // takes several seconds to appear. It used to render nothing at all in that
  // window, which is indistinguishable from "the chips are broken". Show
  // placeholders instead so the wait reads as loading.
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    // Chips used to take ~20s to appear. Two structural reasons, both fixed here:
    //
    //  1. The three source blocks ran one after another (await, await, await)
    //     even though they touch unrelated systems. They now run concurrently.
    //  2. Nothing rendered until every "does this table have rows?" preview had
    //     come back — ~2-2.5s each against live Redshift/Starburst. The row
    //     check exists so an empty table never becomes a chip that demos
    //     nothing, which is worth keeping; it just should not gate first paint.
    //
    // So: fetch the three inventories in parallel, render immediately, then
    // drop the empty ones as their checks resolve. Chips appear in ~2s and the
    // final set is identical to before.
    async function load() {
      const [rsTables, rsRoutines, sbTables] = await Promise.all([
        explorerApi.redshiftTables(REDSHIFT_CHIP_SCHEMA).catch(() => []),
        explorerApi.redshiftRoutines(REDSHIFT_CHIP_SCHEMA).catch(() => []),
        explorerApi
          .starburstTables(STARBURST_CHIP_CATALOG, STARBURST_CHIP_SCHEMA)
          .catch(() => []),
      ]);
      if (cancelled) return;

      const schema = REDSHIFT_CHIP_SCHEMA;
      const catalog = STARBURST_CHIP_CATALOG;
      const sbSchema = STARBURST_CHIP_SCHEMA;

      const rsCandidates = rsTables.slice(0, CHIP_LIMIT_PER_SYSTEM);
      const sbCandidates = sbTables.slice(0, CHIP_LIMIT_PER_SYSTEM);

      const collected: Chip[] = [];
      for (const t of rsCandidates) {
        collected.push({
          key: `redshift:${schema}.${t.name}`,
          label: `Redshift \u00b7 ${schema}.${t.name}`,
          system: "redshift",
          kind: "table",
          message: `migrate the ${t.name} table in schema ${schema} and its data`,
        });
      }
      for (const r of rsRoutines.slice(0, ROUTINE_CHIP_LIMIT_PER_SYSTEM)) {
        const kindWord = r.type.toUpperCase() === "PROCEDURE" ? "procedure" : "function";
        collected.push({
          key: `redshift-routine:${schema}.${r.name}`,
          label: `Redshift \u00b7 ${schema}.${r.name} (${kindWord})`,
          system: "redshift",
          kind: "routine",
          ref: {
            system: "redshift",
            schema,
            name: r.name,
            routineType: r.type,
            label: `Redshift \u00b7 ${schema}.${r.name}`,
          },
          // Redshift routines really can be created in Databricks, so this
          // chip migrates rather than only printing SQL.
          message: `migrate the ${r.name} ${r.type.toLowerCase()} in schema ${schema}`,
        });
      }
      for (const t of sbCandidates) {
        collected.push({
          key: `starburst:${catalog}.${sbSchema}.${t.name}`,
          label: `Starburst \u00b7 ${catalog}.${sbSchema}.${t.name}`,
          system: "starburst",
          kind: "table",
          message: `migrate ${catalog}.${sbSchema}.${t.name} and its data`,
        });
      }

      // Starburst UDFs are deliberately NOT offered as chips. The backend
      // rejects Starburst UDF migration with a real 400 — the DDL translators
      // don't cover them — so a chip could only ever open a source view while
      // every neighbouring chip migrates something. A chip that dead-ends is
      // exactly the kind of thing that bites during a demo. They remain
      // browsable in the data explorer.

      setChips(collected);
      setLoading(false);
      if (collected.length === 0) {
        setError("No source objects available to suggest yet.");
        return;
      }

      // Second pass, off the critical path: remove tables that turn out to be
      // empty. Routines are never row-checked — they have no rows by nature.
      const checks = [
        ...rsCandidates.map(
          (t) =>
            [
              `redshift:${schema}.${t.name}`,
              hasRows(() => explorerApi.redshiftPreview(schema, t.name, 1)),
            ] as const,
        ),
        ...sbCandidates.map(
          (t) =>
            [
              `starburst:${catalog}.${sbSchema}.${t.name}`,
              hasRows(() => explorerApi.starburstPreview(catalog, sbSchema, t.name, 1)),
            ] as const,
        ),
      ];
      const results = await Promise.all(checks.map(async ([key, p]) => [key, await p] as const));
      if (cancelled) return;
      // Set<string>, not the inferred template-literal union — chip keys are
      // plain strings at the comparison site.
      const empty = new Set<string>(results.filter(([, ok]) => !ok).map(([key]) => key));
      if (empty.size > 0) setChips((prev) => prev.filter((c) => !empty.has(c.key)));
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const needle = filter.trim().toLowerCase();
  const visible = needle ? chips.filter((c) => c.label.toLowerCase().includes(needle)) : chips;

  if (loading && chips.length === 0) {
    return (
      <div className="object-chips-row" aria-busy="true" aria-label="Loading suggested source objects">
        <span className="chip-skeleton" style={{ width: "13em" }} />
        <span className="chip-skeleton" style={{ width: "16em" }} />
        <span className="chip-skeleton" style={{ width: "11em" }} />
        <span className="muted chip-loading-note">Checking live source objects…</span>
      </div>
    );
  }

  if (chips.length === 0 && !error) return null;

  return (
    <div className="object-chips-row" aria-label="Suggested source objects — tables migrate, routines show their source">
      {error && chips.length === 0 && <span className="muted">{error}</span>}
      {visible.length === 0 && chips.length > 0 && <span className="muted">No matching objects.</span>}
      {visible.map((c) =>
        c.kind === "routine" ? (
          <button
            key={c.key}
            type="button"
            className={`object-chip object-chip-routine object-chip-${c.system}`}
            disabled={disabled}
            onClick={() => (c.message ? onPick(c.message) : onShowSource(c.ref))}
            title={
              c.message
                ? `Migrate ${c.ref.label} — creates it in Databricks`
                : `Show the real source of ${c.ref.label} (Starburst UDFs can't be migrated)`
            }
          >
            <span className="object-chip-glyph type-glyph-routine" aria-hidden="true">
              <Icon name="function" size={13} />
            </span>
            {c.label}
          </button>
        ) : (
          <button
            key={c.key}
            type="button"
            className={`object-chip object-chip-${c.system}`}
            disabled={disabled}
            onClick={() => onPick(c.message)}
            title={`Send "${c.message}" to chat`}
          >
            {c.label}
          </button>
        ),
      )}
    </div>
  );
}
