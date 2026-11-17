import type { Estimate, Run } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

/** Whether a run still has work to do, so its progress keeps changing. */
export function isActive(run: Pick<Run, "status">): boolean {
  return run.status === "queued" || run.status === "running" || run.status === "stopping";
}

/** The runs as pieces of work, newest first: each its latest attempt, then the runs it resumes. */
export function attempts(runs: Run[]): Run[][] {
  const byId = new Map(runs.map((r) => [r.id, r]));
  const resumed = new Set(runs.map((r) => r.resumes));
  return runs
    .filter((r) => !resumed.has(r.id))
    .map((latest) => {
      const chain = [latest];
      for (let r = byId.get(latest.resumes ?? ""); r; r = byId.get(r.resumes ?? "")) chain.push(r);
      return chain;
    });
}

/** What resuming a run would ask, for its button: e.g. "Continue · 64 left, retry 3 failed".
 * Nothing when there is nothing left to ask. */
export function resumeLabel(estimate: Pick<Estimate, "calls" | "failed_before">): string | null {
  const retry = estimate.failed_before;
  const left = estimate.calls - retry;
  if (left > 0 && retry > 0)
    return `Continue · ${formatNumber(left)} left, retry ${formatNumber(retry)} failed`;
  if (left > 0) return `Continue · ${formatNumber(left)} left`;
  if (retry > 0) return `Retry ${formatNumber(retry)} failed`;
  return null;
}
