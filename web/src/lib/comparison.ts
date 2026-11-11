import type { Comparison } from "@/lib/api/client";
import type { WhereFilter } from "@/lib/sql";

export type InspectRows = (filters: WhereFilter[], columns: string[]) => void;
export type Pair = Comparison["pairs"][number];
export type ReferenceMetrics = NonNullable<Comparison["reference"]>[number];

export function percent(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

export const metric = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("en-US", { maximumSignificantDigits: 4 });

/** Rows where either answer, or both, is missing. */
export function missingRows(pair: Pair): number {
  return Object.values(pair.coverage).reduce((n, v) => n + v.rows, 0);
}

/**
 * The crosstab as a matrix: the pair's first column runs down, the second across.
 * When the server truncated the crosstab, totals only count the cells shown, and precision and
 * recall come from the server's reference metrics instead of the shown cells.
 */
export function crosstabMatrix(comparison: Comparison, metrics: ReferenceMetrics | undefined) {
  const cells = comparison.crosstab ?? [];
  const cellMap = new Map(cells.map((c) => [JSON.stringify(c.values), c]));
  const complete = !comparison.crosstab_completeness?.truncated;
  const cell = (row: string, col: string) => cellMap.get(JSON.stringify([row, col]));
  const rowTotal = (row: string) =>
    cells.filter((c) => c.values[0] === row).reduce((n, c) => n + c.rows, 0);
  const columnTotal = (col: string) =>
    cells.filter((c) => c.values[1] === col).reduce((n, c) => n + c.rows, 0);
  return {
    cells,
    complete,
    down: [...new Set(cells.map((c) => c.values[0]))].sort(),
    across: [...new Set(cells.map((c) => c.values[1]))].sort(),
    cell,
    rowTotal,
    columnTotal,
    represented: cells.reduce((sum, c) => sum + c.rows, 0),
    /** The largest off-diagonal cell, which sets the strongest tint. */
    maxError: Math.max(1, ...cells.filter((c) => c.values[0] !== c.values[1]).map((c) => c.rows)),
    precision: (label: string) =>
      complete
        ? (cell(label, label)?.rows ?? 0) / rowTotal(label)
        : (metrics?.values.find((v) => v.value === label)?.precision ?? null),
    recall: (label: string) =>
      complete
        ? (cell(label, label)?.rows ?? 0) / columnTotal(label)
        : (metrics?.values.find((v) => v.value === label)?.recall ?? null),
  };
}
