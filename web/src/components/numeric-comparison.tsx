"use client";

import { useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Comparison, type Dataset } from "@/lib/api/client";
import { columnLabel, errorMessage, formatNumber } from "@/lib/format";
import { ident, type WhereFilter } from "@/lib/sql";

/** Numeric summaries use the existing read-only query API, over every finite paired answer. */
export function NumericComparison({
  dataset,
  pair,
  tolerance,
  onFilter,
}: {
  dataset: Dataset;
  pair: Comparison["pairs"][number];
  tolerance: number | null;
  onFilter: (filters: WhereFilter[], columns: string[]) => void;
}) {
  const [a, b] = pair.columns;
  const number = (name: string) =>
    dataset.columns.find((c) => c.name === name)?.type === "DATE"
      ? `date_diff('day', DATE '1970-01-01', ${ident(name)})`
      : `CAST(${ident(name)} AS DOUBLE)`;
  const days = pair.columns.every(
    (name) => dataset.columns.find((c) => c.name === name)?.type === "DATE",
  );
  const delta = `(${number(b)} - ${number(a)})`;
  const finite = pair.columns
    .map((name) => `${ident(name)} IS NOT NULL AND isfinite(${number(name)})`)
    .join(" AND ");
  const buckets = [
    {
      key: "lower",
      label: `${columnLabel(b)} lower`,
      where: `(${pair.disagree}) AND ${delta} < 0`,
      match: false,
    },
    {
      key: "within",
      label:
        tolerance === null
          ? "Exact match"
          : `Within ${formatNumber(tolerance)}${days ? " days" : ""}`,
      where: `NOT (${pair.disagree})`,
      match: true,
    },
    {
      key: "higher",
      label: `${columnLabel(b)} higher`,
      where: `(${pair.disagree}) AND ${delta} > 0`,
      match: false,
    },
    // Exact comparison of mixed types can distinguish 1 from "1.0", even with zero numeric error.
    {
      key: "representation",
      label: "Same number, different representation",
      where: `(${pair.disagree}) AND ${delta} = 0`,
      match: false,
    },
  ];
  const sql = `SELECT count(*) AS paired, avg(${delta}) AS bias, avg(abs(${delta})) AS mae,
    max(abs(${delta})) AS max_error, ${buckets.map((bucket) => `count(*) FILTER (WHERE ${bucket.where}) AS ${bucket.key}`).join(", ")}
    FROM data WHERE ${finite}`;
  const [attempt, setAttempt] = useState(0);
  const version = dataset.run?.done;
  const [result, setResult] = useState<{
    sql: string;
    datasetId: string;
    attempt: number;
    version?: number;
    row?: Record<string, unknown>;
    error?: string;
  }>();
  useEffect(() => {
    let current = true;
    const identity = { sql, datasetId: dataset.id, attempt, version };
    api
      .POST("/v1/datasets/{dataset_id}/query", {
        params: { path: { dataset_id: dataset.id } },
        body: { sql, offset: 0, limit: 1 },
      })
      .then(({ data, error }) => {
        if (current)
          setResult({
            ...identity,
            row: data?.rows[0],
            error: error ? errorMessage(error) : undefined,
          });
      })
      .catch(() => {
        if (current)
          setResult({
            ...identity,
            error: "Could not load numeric differences. Retry when connected.",
          });
      });
    return () => {
      current = false;
    };
  }, [sql, dataset.id, attempt, version]);
  const current =
    result?.sql === sql &&
    result?.datasetId === dataset.id &&
    result?.attempt === attempt &&
    result?.version === version;
  if (current && result.error)
    return (
      <Alert variant="destructive">
        <AlertDescription>{result.error}</AlertDescription>
        <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
          Retry numeric summary
        </Button>
      </Alert>
    );
  if (!current || !result.row)
    return (
      <div role="status" className="flex items-center gap-2 text-muted-foreground">
        <Spinner /> Loading numeric differences…
      </div>
    );
  const row = result.row;
  const n = Number(row.paired);
  if (!n)
    return <p className="py-3 text-muted-foreground">No finite paired answers to summarize.</p>;
  const metric = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString("en-US", { maximumSignificantDigits: 4 })
      : "—";
  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-medium">Numeric differences</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Difference = {columnLabel(b)} − {columnLabel(a)}
          {days ? " (days)" : ""}. Positive means {columnLabel(b)} is higher. All {formatNumber(n)}{" "}
          finite paired rows, not a sample.
        </p>
      </div>
      <dl className="grid grid-cols-3 gap-3 border-y py-3">
        <div>
          <dt className="text-xs text-muted-foreground">Mean difference (bias)</dt>
          <dd className="mt-1 font-medium tabular-nums">
            {Number(row.bias) > 0 ? "+" : ""}
            {metric(row.bias)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Mean absolute error</dt>
          <dd className="mt-1 font-medium tabular-nums">{metric(row.mae)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Largest absolute error</dt>
          <dd className="mt-1 font-medium tabular-nums">{metric(row.max_error)}</dd>
        </div>
      </dl>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Difference bucket / inspect</TableHead>
            <TableHead>Share of finite pairs</TableHead>
            <TableHead className="text-right">Rows</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {buckets
            .filter((bucket) => bucket.key !== "representation" || Number(row[bucket.key]) > 0)
            .map((bucket) => {
              const count = Number(row[bucket.key]);
              return (
                <TableRow key={bucket.key}>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="justify-start px-0 text-xs"
                      disabled={!count}
                      onClick={() =>
                        onFilter(
                          [
                            {
                              where: `(${finite}) AND (${bucket.where})`,
                              label: `${bucket.label} · ${tolerance === null ? "exact comparison" : `tolerance ${tolerance}`}`,
                            },
                          ],
                          pair.columns,
                        )
                      }
                    >
                      {bucket.label}
                    </Button>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Progress
                        value={(100 * count) / n}
                        aria-label={bucket.label}
                        className={`w-32 ${bucket.match ? "" : "[&_[data-slot=progress-indicator]]:bg-muted-foreground"}`}
                      />
                      <span className="text-xs tabular-nums">
                        {((100 * count) / n).toFixed(1)}%
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(count)}</TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">
        Lower / higher buckets contain only differences outside the comparison rule. Accent marks
        matches. Missing answers and non-finite numbers are excluded
        {n !== pair.compared ? ` (${formatNumber(pair.compared - n)} non-finite pairs)` : ""}.
      </p>
    </section>
  );
}
