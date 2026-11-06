import type { Dataset } from "@/lib/api/client";

type RunState = Pick<NonNullable<Dataset["run"]>, "status">;

/** Whether a run still has work to do, so its progress keeps changing. */
export function isActive(run: RunState): boolean {
  return run.status === "queued" || run.status === "running" || run.status === "stopping";
}
