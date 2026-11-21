import type { Run } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

// How long to wait after one poll's answer before the next.
const POLL_SECONDS = 2;

/** Call `load` again and again while runs go, each time a while after the last one answered, so
 * slow answers never pile up, and not while the tab is hidden. Returns the function that stops it,
 * for an effect's cleanup. */
export function poll(load: () => Promise<unknown>): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout>;
  const next = () => {
    timer = setTimeout(async () => {
      try {
        if (!document.hidden) await load();
      } finally {
        // A load that throws (the network dropped) doesn't end the polling.
        if (!stopped) next();
      }
    }, POLL_SECONDS * 1000);
  };
  next();
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

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

/** What resuming an ended run does, for its button: "Continue" (after a stop or an interruption)
 * or "Retry 3 failed", or both. Nothing when it went through without a failure. How many a
 * continue asks isn't told: the chunk under way when it stopped is asked again, and cells another
 * run answered since are skipped. */
export function resumeLabel(run: Pick<Run, "status" | "costs">): string | null {
  if (isActive(run)) return null;
  const failed = formatNumber(run.costs.reduce((n, c) => n + c.failed, 0));
  const anyFailed = failed !== "0";
  if (run.status !== "done") return anyFailed ? `Continue, retry ${failed} failed` : "Continue";
  return anyFailed ? `Retry ${failed} failed` : null;
}
