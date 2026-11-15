import type { Run } from "@/lib/api/client";

/** Whether a run still has work to do, so its progress keeps changing. */
export function isActive(run: Pick<Run, "status">): boolean {
  return run.status === "queued" || run.status === "running" || run.status === "stopping";
}
