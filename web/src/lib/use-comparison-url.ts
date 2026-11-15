"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { AnswerColumn, Column } from "@/lib/api/client";
import { comparableColumns, modelGroup, parseComparedColumns } from "@/lib/comparison";

/**
 * The dataset's columns, as the same array for as long as their names and types stay the same. The
 * dataset is polled during runs, which gives new arrays each second; a comparison must not be
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
    rows?: "common" | "pairwise";
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
    if (next.rows) {
      if (next.rows === "pairwise") query.set("rows", "pairwise");
      else query.delete("rows");
    }
    window.history.replaceState(null, "", `/?${query}`);
  }

  return {
    columns,
    reference,
    tolerance: params.get("tolerance") ?? "",
    ignoreCase: params.get("ignore_case") === "true",
    trimWhitespace: params.get("trim_whitespace") === "true",
    rows: params.get("rows") === "pairwise" ? ("pairwise" as const) : ("common" as const),
    change,
    // Whether the address changed since this render, e.g. by a rule change in the same event turn.
    urlChanged: () => params.toString() !== new URLSearchParams(window.location.search).toString(),
  };
}

/** Pre-select the newest task several models answered when the URL doesn't choose columns yet. */
export function useDefaultColumns(answers: AnswerColumn[]) {
  const router = useRouter();
  const params = useSearchParams();
  const group = JSON.stringify(modelGroup(answers));
  const chosen = params.has("compare");
  useEffect(() => {
    if (chosen || group === "[]") return;
    const query = new URLSearchParams(window.location.search);
    query.set("compare", group);
    router.replace(`/?${query}`, { scroll: false });
  }, [chosen, group, router]);
}
