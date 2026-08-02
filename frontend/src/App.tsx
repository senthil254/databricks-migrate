import { useEffect, useState, useCallback } from "react";
import { api, type Run } from "./api";
import { RunList } from "./RunList";
import { RunDetail } from "./RunDetail";
import { Explorer } from "./Explorer";
import { HistoryList } from "./HistoryList";
import { ChatPanel } from "./ChatPanel";
import { UnityCatalogView } from "./UnityCatalogView";
import { DataExplorerPanel } from "./DataExplorerPanel";
import { MigrationActionsProvider } from "./MigrationActions";
import { PreviewProvider, PreviewPane } from "./PreviewPane";
import { Icon, type IconName } from "./Icon";
import { useTheme } from "./useTheme";
import "./theme.css";
import "./index.css";

type Section = "migrations" | "chat" | "intelligence" | "catalog" | "logs";

const SECTIONS: {
  key: Section;
  label: string;
  icon: IconName;
  title: string;
  subtitle: string;
}[] = [
  {
    key: "migrations",
    label: "Migrations",
    icon: "migrate",
    title: "Migrations",
    subtitle:
      "Drag a real Redshift or Starburst object onto the target zone — tables and views create the real Databricks object and copy their rows. No mock data anywhere on this page.",
  },
  {
    key: "chat",
    label: "AI Command",
    icon: "chat",
    title: "AI Command",
    subtitle:
      "Natural-language instruction → reviewable plan → confirm → execute, through the same real adapter every other section uses.",
  },
  {
    key: "intelligence",
    label: "Intelligence",
    icon: "spark",
    title: "Intelligence",
    subtitle:
      "Real Lakebridge CLI operations over the local sample files — transpile, analyze, and reconcile with live validation verdicts.",
  },
  {
    key: "catalog",
    label: "Unity Catalog",
    icon: "catalog",
    title: "Unity Catalog",
    subtitle: "Browse real Databricks catalogs, schemas and tables, and preview migrated data.",
  },
  {
    key: "logs",
    label: "Logs",
    icon: "logs",
    title: "Logs",
    subtitle:
      "Unified history across every run, migration and batch, plus real reconcile validation results and per-run event logs.",
  },
];

// G18 — hidden from the rail at the user's request. The sections themselves
// stay mounted and fully functional (Logs still links into "intelligence" to
// open a run's event log), so re-enabling is deleting a name from this set.
const HIDDEN_SECTIONS = new Set<Section>(["intelligence", "catalog"]);

function BrandMark() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <Icon name="migrate" size={18} />
      </span>
      <span className="brand-text">
        <strong>Lakebridge</strong>
        <small>Migration console</small>
      </span>
    </div>
  );
}

export default function App() {
  const [section, setSection] = useState<Section>("migrations");
  // G19 — the data explorer is a rail nav item now, sitting directly under
  // "Migrations" and above "AI Command", rather than a column inside the
  // Migrations page. It expands in place and the rail widens to hold it; the
  // trees stay mounted whichever section is showing, so a Redshift schema you
  // expanded is still expanded when you come back from chat.
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Real connectivity signal: this poll is the app's only continuous backend
  // call, so its success/failure genuinely reflects adapter reachability. Not
  // a decorative "online" badge.
  const [adapterUp, setAdapterUp] = useState<boolean | null>(null);
  const { theme, toggleTheme } = useTheme();

  const refresh = useCallback(() => {
    api
      .listRuns()
      .then((r) => {
        setRuns(r);
        setAdapterUp(true);
      })
      .catch((e) => {
        setError(String(e));
        setAdapterUp(false);
      });
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  async function trigger(name: string, fn: () => Promise<{ run_id: string }>) {
    setBusy(name);
    setError(null);
    try {
      const { run_id } = await fn();
      refresh();
      setSelected(run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const active = SECTIONS.find((s) => s.key === section)!;

  return (
    <MigrationActionsProvider>
      <PreviewProvider>
      <div className={`shell ${explorerOpen ? "shell-explorer-open" : ""}`}>
        <nav className="rail" aria-label="Sections">
          <BrandMark />

          <ul className="rail-nav">
            {SECTIONS.filter((s) => !HIDDEN_SECTIONS.has(s.key)).map((s) => (
              <li key={s.key} className={s.key === "migrations" ? "rail-group" : undefined}>
                <button
                  className={section === s.key ? "rail-item active" : "rail-item"}
                  aria-current={section === s.key ? "page" : undefined}
                  onClick={() => {
                    setSection(s.key);
                    if (s.key === "intelligence") setSelected(null);
                  }}
                >
                  <Icon name={s.icon} size={18} />
                  <span className="rail-label">{s.label}</span>
                </button>

                {/* The explorer nav item belongs to Migrations — it is rendered
                    inside that <li> so it reads as a child of it, and so it
                    always lands between "Migrations" and "AI Command". */}
                {s.key === "migrations" && (
                  <>
                    <button
                      className={`rail-item rail-subitem ${explorerOpen ? "open" : ""}`}
                      aria-expanded={explorerOpen}
                      onClick={() => setExplorerOpen((o) => !o)}
                    >
                      <Icon name="chevron" size={14} className={`rail-caret ${explorerOpen ? "open" : ""}`} />
                      <Icon name="database" size={16} />
                      <span className="rail-label">Data explorer</span>
                    </button>

                    {/* Display-toggled, never unmounted: unmounting would throw
                        away every tree's fetched expansion state. Also still
                        the app's ONLY DataExplorerPanel mount. */}
                    <div className="rail-explorer" style={{ display: explorerOpen ? "block" : "none" }}>
                      <DataExplorerPanel collapsed={false} onToggleCollapsed={() => setExplorerOpen(false)} />
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>

          <div className="rail-foot">
            <button className="rail-item rail-theme" onClick={toggleTheme}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
              <span className="rail-label">{theme === "dark" ? "Light" : "Dark"}</span>
            </button>
          </div>
        </nav>

        <main className="main">
          <header className="topbar">
            <div className="topbar-titles">
              <h1>{active.title}</h1>
              <p className="topbar-sub">{active.subtitle}</p>
            </div>
            <span
              className={`pill ${adapterUp === false ? "state-failed" : adapterUp ? "state-ok pill-live" : "state-queued"}`}
              title="Reflects the live /runs poll — not a decorative badge"
            >
              <span className="pill-dot" />
              {adapterUp === false ? "Adapter unreachable" : adapterUp ? "Adapter live" : "Connecting"}
            </span>
          </header>

          {/* Every section stays mounted; only CSS display toggles visibility.
              Never revert to conditional unmounting (`{section === "x" && …}`)
              — it destroys the trees' fetched state and every in-flight job
              poll this app tracks. */}
          {/* G19 — the centre-pane preview. It sits above the section content
              rather than inside any one section, because the explorer that
              opens it lives in the rail and is reachable from every section.
              It renders nothing at all when no preview is open, so it costs
              the drop zone no space in the normal case. */}
          <div className="content">
            <PreviewPane />

            <div className="fade-up" style={{ display: section === "migrations" ? "block" : "none" }}>
              <Explorer />
            </div>

            <div className="fade-up" style={{ display: section === "chat" ? "block" : "none" }}>
              <ChatPanel />
            </div>

            <div className="fade-up" style={{ display: section === "catalog" ? "block" : "none" }}>
              {/* Reachable only by direct state change; hidden from the rail
                  (see HIDDEN_SECTIONS). Kept mounted, not deleted. */}
              <UnityCatalogView onRevealInExplorer={() => setSection("migrations")} />
            </div>

            <div className="fade-up" style={{ display: section === "logs" ? "block" : "none" }}>
              <HistoryList
                onOpenRun={(runId) => {
                  setSection("intelligence");
                  setSelected(runId);
                }}
              />
            </div>

            <div className="fade-up" style={{ display: section === "intelligence" ? "block" : "none" }}>
              {error && <p className="error">{error}</p>}

              {!selected && (
                <>
                  <div className="trigger-bar">
                    <button
                      disabled={!!busy}
                      onClick={() => trigger("describe-transpile", api.startDescribeTranspile)}
                    >
                      <Icon name="code" size={15} />
                      {busy === "describe-transpile" ? "Starting…" : "Describe transpile"}
                    </button>
                    <button disabled={!!busy} onClick={() => trigger("transpile", () => api.startTranspile())}>
                      <Icon name="spark" size={15} />
                      {busy === "transpile" ? "Starting…" : "Transpile samples"}
                    </button>
                    <button disabled={!!busy} onClick={() => trigger("analyze", () => api.startAnalyze())}>
                      <Icon name="logs" size={15} />
                      {busy === "analyze" ? "Starting…" : "Analyze samples"}
                    </button>
                    <button disabled={!!busy} onClick={() => trigger("reconcile", api.startReconcile)}>
                      <Icon name="check" size={15} />
                      {busy === "reconcile" ? "Starting…" : "Reconcile"}
                    </button>
                  </div>

                  <RunList runs={runs} onSelect={setSelected} />
                </>
              )}

              {selected && (
                <RunDetail
                  runId={selected}
                  onBack={() => {
                    setSelected(null);
                    refresh();
                  }}
                />
              )}
            </div>
          </div>
        </main>
      </div>
      </PreviewProvider>
    </MigrationActionsProvider>
  );
}
