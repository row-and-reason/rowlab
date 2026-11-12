"use client";

import { useEffect, useState } from "react";

import { api, type Estimate, type Task } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

/** What running the draft would take and cost, or why it can't run: fetched again as it changes. */
export function useEstimate(
  datasetId: string,
  sql: string,
  tasks: Task[],
  enabled: boolean,
  method: "llm" | "manual",
): { estimate?: Estimate; problem?: string } {
  // What the API says the run would cost, and why it can't start, if it can't: its own answer, or
  // the request's error (e.g. OpenRouter can't be reached).
  const [estimate, setEstimate] = useState<{ estimate?: Estimate; problem?: string }>();
  const key = JSON.stringify([sql, tasks, method]);
  useEffect(() => {
    if (!enabled) return;
    let current = true;
    const timer = setTimeout(() => {
      api
        .POST("/v1/datasets/{dataset_id}/estimate", {
          params: { path: { dataset_id: datasetId } },
          body: { sql, tasks, method },
        })
        .then(({ data, error }) => {
          if (!current) return;
          if (data) setEstimate({ estimate: data, problem: data.problem ?? undefined });
          else setEstimate({ problem: errorMessage(error) });
        });
    }, 500);
    return () => {
      current = false;
      clearTimeout(timer);
    };
    // The key stands for the query and tasks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, key, enabled]);
  return { estimate: estimate?.estimate, problem: estimate?.problem };
}
