// G7 — single frontend-only toggle. false hides the llm-transpile
// experimental Starburst DDL button from the UI without touching the
// backend route or migrate_starburst_ddl (still directly curl-able).
export const SHOW_EXPERIMENTAL_STARBURST = false;

/** Testing tools in the Logs section — currently "reset the migration target
 *  schema back to its demo baseline", used between test runs so the next
 *  migration is visibly new.
 *
 *  OFF unless `VITE_TESTING_TOOLS=1` is set when the dev server starts, so the
 *  default state is invisible. That matters: this destroys migrated objects,
 *  and a destructive control has no business being one stray click away while
 *  presenting. Enabling it needs a deliberate act (restarting with the variable
 *  set), which cannot happen by accident mid-demo.
 *
 *      npm --prefix frontend run dev                        # demo — hidden
 *      VITE_TESTING_TOOLS=1 npm --prefix frontend run dev   # testing — shown
 */
export const SHOW_TESTING_TOOLS =
  (import.meta.env.VITE_TESTING_TOOLS ?? "").trim() === "1";
