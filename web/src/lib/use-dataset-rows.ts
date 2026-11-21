"use client";

import { useEffect, useMemo, useState } from "react";

import { api, type QueryResult } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

/**
 * One page of the rows `sql` picks, with only `columns` of the dataset's (all of them without it),
 * fetched again when `version` changes. `result` answers the current request or an earlier one;
 * `shown` is the last good page, kept on screen while the next one loads.
 */
export function useDatasetRows(
  datasetId: string,
  sql: string,
  columns: string[] | undefined,
  page: number,
  pageSize: number,
  version?: number,
) {
  // Each result remembers the request it answers, so a stale response is never shown as current.
  // The request by value: the dataset is fetched anew as runs go, with the same columns.
  const body = JSON.stringify({ sql, columns, offset: page * pageSize, limit: pageSize });
  const request = useMemo(
    () => JSON.parse(body) as { sql: string; columns?: string[]; offset: number; limit: number },
    [body],
  );
  const [result, setResult] = useState<{
    request: typeof request;
    data?: QueryResult;
    error?: string;
  }>();

  useEffect(() => {
    let current = true;
    api
      .POST("/v1/datasets/{dataset_id}/query", {
        params: { path: { dataset_id: datasetId } },
        body: request,
      })
      .then(({ data, error }) => {
        if (current) setResult(error ? { request, error: errorMessage(error) } : { request, data });
      });
    return () => {
      current = false;
    };
  }, [datasetId, request, version]);

  const [shown, setShown] = useState<QueryResult>();
  if (result?.data && result.data !== shown) setShown(result.data);

  return { result, shown, loading: result?.request !== request };
}
