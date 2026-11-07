"use client";

import { useEffect, useState } from "react";
import { api, type Comparison } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import type { components } from "@/lib/api/schema";

export type ComparisonActions = {
  setReady?: (ready: boolean) => void;
  rules?: () => void;
  columns?: () => void;
  different?: () => void;
};

export type CompareRequest = components["schemas"]["CompareRequest"];

/** A result belongs to one request. Old counts must never act on a newly selected comparison. */
export function useComparison(
  datasetId: string,
  request: CompareRequest | undefined,
  version?: number,
) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    datasetId: string;
    request: CompareRequest;
    attempt: number;
    version?: number;
    data?: Comparison;
    error?: string;
  }>();
  useEffect(() => {
    if (!request) return;
    let current = true;
    const identity = { datasetId, request, attempt, version };
    api
      .POST("/v1/datasets/{dataset_id}/compare", {
        params: { path: { dataset_id: datasetId } },
        body: request,
      })
      .then(({ data, error }) => {
        if (current)
          setResult({ ...identity, data, error: error ? errorMessage(error) : undefined });
      })
      .catch(() => {
        if (current)
          setResult({
            ...identity,
            error: "Could not load the comparison. Check your connection and retry.",
          });
      });
    return () => {
      current = false;
    };
  }, [datasetId, request, attempt, version]);
  const fresh =
    result?.datasetId === datasetId &&
    result?.request === request &&
    result?.attempt === attempt &&
    result?.version === version;
  return {
    data: fresh ? result?.data : undefined,
    error: fresh ? result?.error : undefined,
    retry: () => setAttempt((n) => n + 1),
  };
}
