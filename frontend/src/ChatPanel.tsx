import { useEffect, useRef, useState } from "react";
import { api, type Run } from "./api";
import { explorerApi, type Migration } from "./explorerApi";
import { batchApi, type BatchSummary } from "./batchApi";
import { chatApi, type ChatAction, type ChatExecuteResult, type ChatPlanUnderstood } from "./chatApi";
import { ConfirmDialog } from "./ConfirmDialog";
import { MigrationCard, type Job } from "./MigrationCard";
import { BatchCard } from "./BatchCard";
import { STATUS_META } from "./statusMeta";
import { ObjectChips, type RoutineRef } from "./ObjectChips";
import { Icon } from "./Icon";
import { Collapsible, ScrollBox } from "./Collapsible";

// G6 — chat-style UI over the real /chat/plan -> /chat/execute contract.
// Every plan is a review artifact only (never auto-executed); execution
// requires an explicit ConfirmDialog confirm, reusing the same G5
// accessibility-hardened dialog component the Explorer tab already uses.
// Terminal-state results are polled from the SAME existing endpoints the
// Explorer/Batches/History tabs already poll (GET /migrations/{id},
// GET /batches/{id}, GET /runs/{id}) — no new status-polling logic is
// invented here.

type Role = "user" | "system";

interface PlanMessage {
  role: "system";
  kind: "plan";
  id: string;
  plan: ChatPlanUnderstood;
  planState: "pending" | "confirmed" | "cancelled";
  execResult: ChatExecuteResult | null;
  execError: string | null;
}

interface RefusalMessage {
  role: "system";
  kind: "refusal";
  id: string;
  reason: string;
}

interface TextMessage {
  role: Role;
  kind: "text";
  id: string;
  text: string;
}

interface ErrorMessage {
  role: "system";
  kind: "error";
  id: string;
  text: string;
}

// G18 — routine source shown in-transcript from a routine chip click. This is
// a read-only view of the REAL source (Redshift SHOW PROCEDURE / pg_proc.prosrc,
// Starburst SHOW CREATE FUNCTION). It deliberately carries no "create in
// destination" action — the user decided: show SQL only for now.
interface SourceMessage {
  role: "system";
  kind: "source";
  id: string;
  ref: RoutineRef;
  source: string | null;
  /** Backend's `source_available`; only some routes send it. undefined = not stated. */
  available: boolean | undefined;
  error: string | null;
}

type Message = PlanMessage | RefusalMessage | TextMessage | ErrorMessage | SourceMessage;

function describeAction(action: ChatAction): string {
  switch (action.kind) {
    case "migrate_ddl":
      return `Migrate DDL: ${action.source_system} ${action.schema}.${action.name} (${action.object_type})`;
    case "copy_table_data":
      return `Copy real row data: ${action.source_system} ${action.schema}.${action.name}`;
    case "migrate_schema_batch":
      return `Batch-migrate schema ${action.schema} (${action.item_count} real objects${action.include_data ? ", including row data" : ""})`;
    case "reconcile":
      return "Dispatch the configured reconcile job";
    case "migrate_table_and_data":
      return `Migrate ${action.source_system} ${action.schema}.${action.name} (${action.object_type}) and copy its real row data`;
  }
}

let msgCounter = 0;
function nextId() {
  msgCounter += 1;
  return `m${msgCounter}`;
}

// G18 progress primitives. Real migrations here take 20-40s, so every wait
// gets an animated in-transcript indicator (a static label reads as frozen)
// and, where a start time is known, a live elapsed counter. The animation is
// CSS-only and is disabled by the `prefers-reduced-motion` block appended to
// index.css, per the design contract.

function ElapsedSeconds({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return <>{Math.max(0, Math.round((now - since) / 1000))}s</>;
}

function WorkingIndicator({ label, since }: { label: string; since?: number }) {
  return (
    <p className="chat-working" role="status" aria-live="polite">
      <span className="chat-working-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className="chat-working-label">{label}</span>
      {since !== undefined && (
        <span className="chat-working-elapsed mono">
          <ElapsedSeconds since={since} />
        </span>
      )}
    </p>
  );
}

// After this many consecutive failed polls we stop hiding the failure. We do
// NOT stop polling — the run may still be progressing server-side; the user
// just deserves to know the status they're looking at is stale.
const POLL_FAIL_NOTICE_AT = 3;

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmingPlanMsgId, setConfirmingPlanMsgId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Live-updated polling results, keyed by message id.
  const [migrationById, setMigrationById] = useState<Record<string, Migration>>({});
  const [batchById, setBatchById] = useState<Record<string, BatchSummary>>({});
  const [runById, setRunById] = useState<Record<string, Run>>({});
  // G18: when the plan request is in flight, so the transcript (where the user
  // is actually looking) shows something, not just the send button.
  const [planPendingSince, setPlanPendingSince] = useState<number | null>(null);
  // G18: execution start time per plan message, for the elapsed counter.
  const [execStartedAt, setExecStartedAt] = useState<Record<string, number>>({});
  // G18: consecutive poll failures per message. Previously swallowed entirely.
  const [pollFailures, setPollFailures] = useState<Record<string, number>>({});
  // G19: a finished migration card is tall (plan text + pipeline + output SQL),
  // so a few of them bury the input. Each plan card can be folded to its title
  // line. Keyed by message id; absent = expanded.
  const [foldedCards, setFoldedCards] = useState<Record<string, boolean>>({});

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, planPendingSince]);

  function appendMessage(msg: Message) {
    setMessages((prev) => [...prev, msg]);
  }

  // `override` lets ObjectChips send a fully-formed natural-language
  // request (e.g. "migrate schema.table and its data") through the exact
  // same /chat/plan -> ConfirmDialog -> /chat/execute path a typed message
  // uses — no separate immediate-execute path for chip clicks.
  async function submitInstruction(override?: string) {
    const text = (override ?? instruction).trim();
    if (!text || busy) return;
    setInstruction("");
    appendMessage({ role: "user", kind: "text", id: nextId(), text });
    setBusy(true);
    setPlanPendingSince(Date.now());
    try {
      const resp = await chatApi.plan(text);
      if (resp.understood) {
        appendMessage({
          role: "system",
          kind: "plan",
          id: nextId(),
          plan: resp,
          planState: "pending",
          execResult: null,
          execError: null,
        });
      } else {
        appendMessage({ role: "system", kind: "refusal", id: nextId(), reason: resp.reason });
      }
    } catch (e) {
      appendMessage({
        role: "system",
        kind: "error",
        id: nextId(),
        text: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setPlanPendingSince(null);
      setBusy(false);
    }
  }

  // G18 — a routine chip click. Explicitly NOT submitInstruction: no plan is
  // built, nothing is migrated. We append a placeholder message immediately so
  // the transcript reacts at once, then fill in the real fetched source.
  async function showRoutineSource(ref: RoutineRef) {
    const id = nextId();
    appendMessage({ role: "system", kind: "source", id, ref, source: null, available: undefined, error: null });
    try {
      const res =
        ref.system === "starburst"
          ? await explorerApi.starburstUdfSource(ref.name)
          : await explorerApi.redshiftRoutineSource(ref.schema ?? "", ref.name);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id && m.kind === "source"
            ? { ...m, source: res.source, available: res.source_available }
            : m,
        ),
      );
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id && m.kind === "source"
            ? { ...m, error: e instanceof Error ? e.message : String(e) }
            : m,
        ),
      );
    }
  }

  function startPolling(msgId: string, result: ChatExecuteResult) {
    const POLL_MS = 1500;
    let stopped = false;

    async function tick() {
      if (stopped) return;
      try {
        if (result.result_type === "migration") {
          // (poll bodies below; a successful pass clears the failure counter)
          const m = await explorerApi.getMigration(result.migration_id);
          setMigrationById((prev) => ({ ...prev, [msgId]: m }));
          if (m.status === "queued" || m.status === "running") setTimeout(tick, POLL_MS);
        } else if (result.result_type === "batch") {
          const b = await batchApi.getBatch(result.batch_id);
          setBatchById((prev) => ({ ...prev, [msgId]: b }));
          if (b.status === "pending" || b.status === "running") setTimeout(tick, POLL_MS);
        } else if (result.result_type === "query" || result.result_type === "mcp_tool_call") {
          // Synchronous results already returned in full by POST /chat/execute —
          // nothing to poll. The result is already attached to the message via
          // execResult (set by confirmExecute before startPolling is called).
        } else {
          const r = await api.getRun(result.run_id);
          setRunById((prev) => ({ ...prev, [msgId]: r }));
          if (r.status === "queued" || r.status === "running") setTimeout(tick, POLL_MS);
        }
        setPollFailures((prev) => (prev[msgId] ? { ...prev, [msgId]: 0 } : prev));
      } catch {
        // G18: this used to swallow the error entirely, so a permanently
        // failing poll showed nothing at all. Keep polling (the work may still
        // be progressing server-side) but stop hiding the failure.
        setPollFailures((prev) => ({ ...prev, [msgId]: (prev[msgId] ?? 0) + 1 }));
        if (!stopped) setTimeout(tick, POLL_MS);
      }
    }

    tick();
    return () => {
      stopped = true;
    };
  }

  async function confirmExecute(msgId: string, plan: ChatPlanUnderstood) {
    setConfirmingPlanMsgId(null);
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId && m.kind === "plan" ? { ...m, planState: "confirmed" } : m)),
    );
    // G18: execution never set `busy`, so the input stayed live while a real
    // migration ran. It does now, and the start time drives the elapsed counter.
    setBusy(true);
    setExecStartedAt((prev) => ({ ...prev, [msgId]: Date.now() }));
    try {
      const result = await chatApi.execute(plan.plan_id);
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId && m.kind === "plan" ? { ...m, execResult: result } : m)),
      );
      startPolling(msgId, result);
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId && m.kind === "plan"
            ? { ...m, execError: e instanceof Error ? e.message : String(e) }
            : m,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  function cancelPlan(msgId: string) {
    setConfirmingPlanMsgId(null);
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId && m.kind === "plan" ? { ...m, planState: "cancelled" } : m)),
    );
  }

  const confirmingMsg = messages.find(
    (m) => m.id === confirmingPlanMsgId && m.kind === "plan",
  ) as PlanMessage | undefined;

  return (
    <div className="chat-panel">
      <div className="chat-panel-main">
      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-hero">
            <span className="chat-hero-mark" aria-hidden="true">
              <Icon name="chat" size={30} />
            </span>
            <h2 className="chat-hero-title">Ask for a migration</h2>
            <p className="chat-hero-lede">
              Type an instruction like <em>migrate the venue table</em> or <em>reconcile</em>, or click a
              chip below. Every instruction produces a real reviewable plan against the live object
              inventory — nothing executes until you confirm it.
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`chat-msg chat-msg-${m.role}`}>
            {m.kind === "text" && <p>{m.text}</p>}

            {m.kind === "refusal" && (
              <div className="callout-warn">
                <strong>Not understood:</strong> {m.reason}
              </div>
            )}

            {m.kind === "error" && (
              <div className="callout-warn">
                <strong>Request failed:</strong> {m.text}
              </div>
            )}

            {m.kind === "source" && (
              <div className="chat-source-card">
                <div className="chat-source-head">
                  <span className={`object-chip-glyph type-glyph-routine`} aria-hidden="true">
                    <Icon name="function" size={13} />
                  </span>
                  <strong>{m.ref.label}</strong>
                  <span className="muted">
                    {m.ref.system === "starburst" ? "Starburst / Trino" : "Redshift"} ·{" "}
                    {m.ref.routineType.toLowerCase()}
                  </span>
                </div>
                {m.error && (
                  <div className="callout-warn">
                    <strong>Could not read source:</strong> {m.error}
                  </div>
                )}
                {!m.error && m.source === null && <p className="empty">Loading real source…</p>}
                {/* Honesty: when the backend says the body isn't available, say so
                    rather than presenting whatever text came back as a real body. */}
                {m.available === false && (
                  <div className="callout-warn">
                    Source body not available from this system — anything shown below is a signature or
                    placeholder, not the real routine body.
                  </div>
                )}
                {/* G19: was a bare <pre> — now collapsible with its own
                    scrollbars, matching every other SQL display. */}
                {m.source !== null && (
                  <Collapsible title="Source SQL" meta={`${m.source.split("\n").length} lines`}>
                    <ScrollBox variant="code">
                      <pre className="mono code-block source-code-block">{m.source}</pre>
                    </ScrollBox>
                  </Collapsible>
                )}
                {/* No create-in-destination button here, by explicit decision. */}
              </div>
            )}

            {m.kind === "plan" && (() => {
              const folded = !!foldedCards[m.id];
              const mig = migrationById[m.id];
              // Only offer folding once there is something worth folding — a
              // plan still awaiting confirmation is short and must stay visible.
              const foldable = !!m.execResult || !!m.execError;
              const summary = mig
                ? `${mig.object_name} — ${mig.status}`
                : m.execError
                  ? "execution failed"
                  : "done";
              return (
              <div className={`chat-plan-card ${folded ? "folded" : ""}`}>
                <div className="chat-plan-head">
                  <span className="eyebrow">Proposed plan</span>
                  <h4 className="chat-plan-title">{describeAction(m.plan.action)}</h4>
                </div>

                {folded && (
                  <p className="muted chat-plan-summary mono">{summary}</p>
                )}

                <div className="chat-plan-body" style={{ display: folded ? "none" : "block" }}>
                <p className="chat-plan-why">{m.plan.explanation}</p>
                <p className="chat-plan-endpoint mono">{m.plan.endpoint}</p>

                {m.planState === "pending" && (
                  <button className="chat-plan-confirm" onClick={() => setConfirmingPlanMsgId(m.id)}>
                    Review &amp; confirm
                  </button>
                )}
                {m.planState === "cancelled" && <p className="muted">Cancelled — nothing executed.</p>}
                {m.planState === "confirmed" && !m.execResult && !m.execError && (
                  <WorkingIndicator label="Executing on live systems…" since={execStartedAt[m.id]} />
                )}
                {m.execError && (
                  <div className="callout-warn">
                    <strong>Execution failed:</strong> {m.execError}
                  </div>
                )}
                {(pollFailures[m.id] ?? 0) >= POLL_FAIL_NOTICE_AT && (
                  <div className="callout-warn">
                    Still waiting — the last {pollFailures[m.id]} status polls failed, so the state shown
                    below may be stale. Still polling; the work itself may be progressing.
                  </div>
                )}

                {m.execResult?.result_type === "migration" &&
                  (() => {
                    const mig = migrationById[m.id];
                    const job: Job = {
                      key: m.id,
                      system: (mig?.source_system ??
                        ("source_system" in m.plan.action ? m.plan.action.source_system : "redshift")) as
                        | "redshift"
                        | "starburst",
                      objectType: mig?.object_type ?? "",
                      name: mig?.object_name ?? "",
                      // G17 Stage 1 fix: "migrate_table_and_data" previously fell
                      // through to "ddl", so PipelineFlow rendered "Writing target"
                      // as Skipped even though real rows were copied.
                      action:
                        m.plan.action.kind === "copy_table_data"
                          ? "data"
                          : m.plan.action.kind === "migrate_table_and_data"
                            ? "create-and-copy"
                            : "ddl",
                      triggeredAt: "",
                      migration: mig ?? null,
                      clientError: null,
                      settled: !!mig && (mig.status === "completed" || mig.status === "failed"),
                    };
                    return <MigrationCard job={job} />;
                  })()}

                {m.execResult?.result_type === "batch" &&
                  (batchById[m.id] ? (
                    <BatchCard label="Chat batch" batch={batchById[m.id]} />
                  ) : (
                    <WorkingIndicator label="Dispatched — waiting for first poll…" since={execStartedAt[m.id]} />
                  ))}

                {m.execResult?.result_type === "run" &&
                  (() => {
                    const run = runById[m.id];
                    if (!run) return <WorkingIndicator label="Dispatched — waiting for first poll…" since={execStartedAt[m.id]} />;
                    const meta = STATUS_META[run.status];
                    return (
                      <p>
                        <span className={`status-pill ${meta.className}`}>
                          <span aria-hidden="true">{meta.icon}</span> {meta.label}
                        </span>{" "}
                        <span className="muted mono">run {run.id}</span>
                        {run.status === "completed" && (
                          <span className="muted">
                            {" "}
                            — dispatch completed; this reflects the job being dispatched, not that reconciliation
                            necessarily passed. Open History (G4) for the real reconcile result.
                          </span>
                        )}
                      </p>
                    );
                  })()}

                {m.execResult?.result_type === "query" &&
                  (() => {
                    const res = m.execResult as Extract<ChatExecuteResult, { result_type: "query" }>;
                    return (
                      <div className="preview-panel">
                        {res.row_count === 0 ? (
                          <p className="empty">(no rows)</p>
                        ) : (
                          // G19: collapsible, with both scrollbars on the
                          // table's own box rather than an unbounded table.
                          <Collapsible title="Data" meta={`${res.row_count} rows`}>
                          <ScrollBox variant="rows">
                          <table className="run-table pv-table">
                            <thead>
                              <tr>
                                {(res.columns ?? res.rows[0].map((_, j) => `col ${j}`)).map((c, i) => (
                                  <th key={i}>{c}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {res.rows.map((row, i) => (
                                <tr key={i}>
                                  {row.map((cell, j) => (
                                    <td key={j}>{cell === null ? <em>null</em> : String(cell)}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          </ScrollBox>
                          </Collapsible>
                        )}
                      </div>
                    );
                  })()}

                {m.execResult?.result_type === "mcp_tool_call" &&
                  (() => {
                    const res = m.execResult as Extract<ChatExecuteResult, { result_type: "mcp_tool_call" }>;
                    return (
                      <div className="preview-panel">
                        <p className="muted mono">MCP tool: {res.tool_name}</p>
                        <Collapsible title="Result" defaultOpen={false}>
                          <ScrollBox variant="code">
                            <pre className="mono code-block">{JSON.stringify(res.result, null, 2)}</pre>
                          </ScrollBox>
                        </Collapsible>
                      </div>
                    );
                  })()}
                </div>

                {/* G19 — expand/collapse, at the end of the card as asked. */}
                {foldable && (
                  <button
                    className="chat-plan-fold"
                    aria-expanded={!folded}
                    onClick={() => setFoldedCards((prev) => ({ ...prev, [m.id]: !prev[m.id] }))}
                  >
                    <Icon name="chevron" size={12} className={`pv-caret ${folded ? "" : "open"}`} />
                    {folded ? "Expand" : "Collapse"}
                  </button>
                )}
              </div>
              );
            })()}
          </div>
        ))}

        {/* G18: in-transcript pending bubble. Before this, a plan request in
            flight was signalled only by the greyed input and the button label,
            i.e. nowhere near where the user is reading. */}
        {planPendingSince !== null && (
          <div className="chat-msg chat-msg-system">
            <div className="chat-pending-bubble">
              <WorkingIndicator label="Building a plan against the live inventory…" since={planPendingSince} />
            </div>
          </div>
        )}
      </div>

      <ObjectChips
        filter={instruction}
        disabled={busy}
        onPick={(text) => submitInstruction(text)}
        onShowSource={showRoutineSource}
      />

      <form
        className="chat-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          submitInstruction();
        }}
      >
        <input
          type="text"
          value={instruction}
          disabled={busy}
          placeholder="e.g. migrate the venue table"
          onChange={(e) => setInstruction(e.target.value)}
        />
        <button type="submit" disabled={busy || !instruction.trim()} aria-label={busy ? "Working" : "Send instruction"}>
          {/* The button is a fixed 48px square, so a busy *label* overflowed it.
              Spin the existing icon instead — same footprint, still legible as
              "in progress", and the transcript carries the wordy status. */}
          <Icon name={busy ? "refresh" : "arrow-right"} size={16} className={busy ? "spin" : undefined} />
        </button>
      </form>
      </div>

      {confirmingMsg && (
        <ConfirmDialog
          titleId="chat-confirm-title"
          title="Confirm real execution"
          confirmLabel="Execute"
          onCancel={() => cancelPlan(confirmingMsg.id)}
          onConfirm={() => confirmExecute(confirmingMsg.id, confirmingMsg.plan)}
        >
          <p>{describeAction(confirmingMsg.plan.action)}</p>
          <p className="muted">{confirmingMsg.plan.explanation}</p>
          <p className="muted mono">Real call: {confirmingMsg.plan.endpoint}</p>
          <p className="muted">
            This will really execute against live systems — the same adapter the other tabs use, not a preview.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
