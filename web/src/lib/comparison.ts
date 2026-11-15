import type { AnswerColumn, Comparison, Dataset } from "@/lib/api/client";
import { formatUsd } from "@/lib/format";
import { ALL_ROWS, type WhereFilter } from "@/lib/sql";
import type { CompareRequest } from "@/lib/use-comparison";

export type InspectRows = (filters: WhereFilter[], columns: string[]) => void;
export type Pair = Comparison["pairs"][number];
export type ReferenceMetrics = NonNullable<Comparison["reference"]>[number];

export function percent(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

export const metric = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("en-US", { maximumSignificantDigits: 4 });

export const usd = (amount: number | null) => (amount === null ? "—" : formatUsd(amount));

/** A model's accuracy and cost, when the pair is that model against the comparison's reference. */
export function againstReference(comparison: Comparison, pair: Pair) {
  const [column, other] = pair.columns;
  const against = comparison.reference !== null && other === comparison.columns.at(-1);
  return {
    metrics: against ? comparison.reference?.find((r) => r.column === column) : undefined,
    cost: against ? comparison.costs.find((c) => c.column === column) : undefined,
  };
}

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

const NUMERIC = /^(U?TINYINT|U?SMALLINT|U?INTEGER|U?BIGINT|U?HUGEINT|FLOAT|DOUBLE|DECIMAL.*|DATE)$/;

/** Columns a comparison can use: every dataset column except the internal row id. */
export function comparableColumns(columns: Dataset["columns"]): Dataset["columns"] {
  return columns.filter((c) => c.name !== "__row_id");
}

/**
 * The columns to pick from, in groups: each task's answers from models (newest first), labels people
 * set, then the file's own columns; or, for a `reference`, labels and the file's columns first.
 * Those in `leaveOut` aren't offered.
 */
export function columnGroups(
  dataset: Pick<Dataset, "columns" | "answers">,
  leaveOut: (string | null)[] = [],
  { reference = false } = {},
): { label: string; items: { value: string; label: string; detail?: string }[] }[] {
  const offered = (name: string) => !leaveOut.includes(name);
  const answered = new Set(dataset.answers.flatMap((a) => a.columns));
  const fromModels = dataset.answers.filter((a) => a.model);
  const tasks = [...new Set(fromModels.map((a) => a.name))];
  const models = tasks.map((task) => ({
    label: `${task} · models`,
    items: fromModels
      .filter((a) => a.name === task)
      .flatMap((a) => a.columns)
      .filter(offered)
      .map((name) => ({ value: name, label: name })),
  }));
  const labels = {
    label: "Labels",
    items: dataset.answers
      .filter((a) => !a.model)
      .flatMap((a) => a.columns)
      .filter(offered)
      .map((name) => ({ value: name, label: name })),
  };
  const own = {
    label: "The file's columns",
    items: comparableColumns(dataset.columns)
      .filter((c) => !answered.has(c.name) && offered(c.name))
      .map((c) => ({ value: c.name, label: c.name })),
  };
  return reference ? [labels, own, ...models] : [...models, labels, own];
}

/** The `compare` URL value as known, de-duplicated column names. Anything malformed means none. */
export function parseComparedColumns(
  encoded: string | null,
  columns: Dataset["columns"],
): string[] {
  try {
    const parsed: unknown = JSON.parse(encoded ?? "[]");
    return Array.isArray(parsed)
      ? [
          ...new Set(
            parsed.filter(
              (name): name is string =>
                typeof name === "string" &&
                columns.some((c) => c.name === name && name !== "__row_id"),
            ),
          ),
        ]
      : [];
  } catch {
    return [];
  }
}

/** The comparison setup chosen in the URL. */
export type ComparisonChoice = {
  columns: string[];
  reference: string | null;
  tolerance: string;
  ignoreCase: boolean;
  trimWhitespace: boolean;
  rows: CompareRequest["rows"];
};

/**
 * What the chosen columns allow (text rules, a numeric or date tolerance), why the setup can't be
 * compared if it can't, and the compare request once there is something valid to compare.
 */
export function comparisonSetup(choice: ComparisonChoice, datasetColumns: Dataset["columns"]) {
  const { columns, reference, tolerance, ignoreCase, trimWhitespace, rows } = choice;
  const compared = reference ? [...columns, reference] : columns;
  const types = compared.map((name) => datasetColumns.find((c) => c.name === name)!.type);
  const numeric =
    types.length > 0 &&
    types.every((type) => NUMERIC.test(type)) &&
    (types.every((t) => t === "DATE") || types.every((t) => t !== "DATE"));
  const text = types.length > 0 && types.every((t) => t === "VARCHAR");
  const dates = types.length > 0 && types.every((type) => type === "DATE");
  const mixed = new Set(types).size > 1 && !numeric;
  const enough = columns.length >= 2 || (columns.length === 1 && !!reference);
  const problem =
    reference && columns.includes(reference)
      ? "The reference must be different from the compared columns."
      : numeric &&
          tolerance !== "" &&
          (!Number.isFinite(Number(tolerance)) || Number(tolerance) < 0)
        ? "Tolerance must be a finite number of zero or more."
        : undefined;
  const request: CompareRequest | undefined =
    enough && !problem
      ? {
          sql: ALL_ROWS,
          columns,
          reference,
          ignore_case: text && ignoreCase,
          trim_whitespace: text && trimWhitespace,
          tolerance: numeric && tolerance !== "" ? Number(tolerance) : null,
          rows,
        }
      : undefined;
  return { numeric, text, dates, mixed, problem, request };
}

/** The answer columns of the newest task several models answered, to compare them by default. */
export function modelGroup(answers: AnswerColumn[]): string[] {
  const groups = new Map<string, string[]>();
  for (const answer of answers) {
    if (answer.model === null) continue;
    groups.set(answer.name, [...(groups.get(answer.name) ?? []), answer.columns[0]]);
  }
  return [...groups.values()].find((g) => g.length > 1) ?? [];
}
