import type { RunStatus, Command } from "./api";

// Status is always shown as text + icon together — never color alone
// (PLAN.md's original accessibility requirement, still valid).
export const STATUS_META: Record<RunStatus, { label: string; icon: string; className: string }> = {
  queued: { label: "Queued", icon: "○", className: "status-queued" },
  running: { label: "Running", icon: "◐", className: "status-running" },
  completed: { label: "Completed", icon: "✓", className: "status-completed" },
  failed: { label: "Failed", icon: "✗", className: "status-failed" },
};

// Historically reconcile's "completed" meant "job dispatched", not
// "reconciliation finished" (MEMORY.md, G2 entry). That was a real bug,
// fixed in G4 (MEMORY.md's G4 backend entry): the Run now stays "running"
// for real until the dispatched Databricks job reaches a real terminal
// state, so "completed" is now an honest, real terminal signal for
// reconcile too. No command currently needs this caveat — kept as a hook
// in case a future command reintroduces a dispatch-vs-completion gap.
export const DISPATCH_ONLY_COMMANDS: ReadonlySet<Command> = new Set([]);

export function dispatchCaveat(command: Command): string | null {
  if (!DISPATCH_ONLY_COMMANDS.has(command)) return null;
  return "This means the job was dispatched successfully — not that reconciliation itself has finished. Check the Databricks job run for the actual result.";
}
