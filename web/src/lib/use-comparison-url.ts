"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type Column } from "@/lib/api/client";
import { comparableColumns, modelGroup, parseComparedColumns } from "@/lib/comparison";

/**
 * The dataset's columns, as the same array for as long as their names and types stay the same. The
 * dataset list is polled during runs, which gives new arrays each second; a comparison must not be
 * asked again for that.
 */
export function useSameColumns(columns: Column[]): Column[] {
  const [same, setSame] = useState(columns);
  const key = (cs: Column[]) => JSON.stringify(cs.map((c) => [c.name, c.type]));
  if (same !== columns && key(same) !== key(columns)) setSame(columns);
  return same;
}

/** The comparison setup kept in the URL, and a way to change it without adding history entries. */
export function useComparisonUrl(datasetColumns: Column[]) {
  const params = useSearchParams();
  const encoded = params.get("compare");
  const parsed = useMemo(
    () => parseComparedColumns(encoded, datasetColumns),
    [encoded, datasetColumns],
  );
  // The address reaches `params` a render after a pick, so the pick is kept here too: a second quick
  // pick must build on the first, not on the address before it.
  const [columns, setColumns] = useState(parsed);
  const [previous, setPrevious] = useState(parsed);
  if (parsed !== previous) {
    setPrevious(parsed);
    if (JSON.stringify(parsed) !== JSON.stringify(columns)) setColumns(parsed);
  }
  const referenceParam = params.get("reference");
  const reference = comparableColumns(datasetColumns).some((c) => c.name === referenceParam)
    ? referenceParam
    : null;

  function change(next: {
    columns?: string[];
    reference?: string | null;
    tolerance?: string;
    ignore_case?: boolean;
    trim_whitespace?: boolean;
  }) {
    const query = new URLSearchParams(window.location.search);
    if (next.columns) {
      setColumns(next.columns);
      query.set("compare", JSON.stringify(next.columns));
    }
    if (next.reference !== undefined) {
      if (next.reference) query.set("reference", next.reference);
      else query.delete("reference");
    }
    if (next.tolerance !== undefined) {
      if (next.tolerance) query.set("tolerance", next.tolerance);
      else query.delete("tolerance");
    }
    for (const key of ["ignore_case", "trim_whitespace"] as const) {
      if (next[key] !== undefined) {
        if (next[key]) query.set(key, "true");
        else query.delete(key);
      }
    }
    window.history.replaceState(null, "", `/?${query}`);
  }

  return {
    columns,
    reference,
    tolerance: params.get("tolerance") ?? "",
    ignoreCase: params.get("ignore_case") === "true",
    trimWhitespace: params.get("trim_whitespace") === "true",
    change,
    // Whether the address changed since this render, e.g. by a rule change in the same event turn.
    urlChanged: () => params.toString() !== new URLSearchParams(window.location.search).toString(),
  };
}

/** Pre-select the run's model group when the URL doesn't choose columns yet. */
export function useRunDefaultColumns(runId: string | undefined) {
  const router = useRouter();
  const params = useSearchParams();
  // Defaults from a run must not overwrite a selection made while that request was pending.
  const latestParams = useRef(params);
  useEffect(() => {
    latestParams.current = params;
  }, [params]);
  useEffect(() => {
    if (!runId) return;
    let current = true;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })
      .then(({ data }) => {
        if (!current || !data || latestParams.current.has("compare")) return;
        const group = modelGroup(data.columns);
        if (!group.length) return;
        const query = new URLSearchParams(latestParams.current);
        query.set("compare", JSON.stringify(group));
        router.replace(`/?${query}`, { scroll: false });
      })
      .catch(() => {
        /* Manual selection remains available if run defaults cannot load. */
      });
    return () => {
      current = false;
    };
  }, [runId, router]);
}
