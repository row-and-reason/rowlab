"use client";

import { InfoIcon } from "lucide-react";
import { useMemo, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { NumericComparison } from "@/components/numeric-comparison";
import { TooltipButton } from "@/components/tooltip-button";
import { PaneHeader } from "@/components/pane";
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
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { type Comparison, type Dataset } from "@/lib/api/client";
import { columnLabel, formatNumber } from "@/lib/format";
import { ALL_ROWS, ident, type WhereFilter } from "@/lib/sql";
import { useComparison, type ComparisonActions } from "@/lib/use-comparison";

type InspectRows = (filters: WhereFilter[], columns: string[]) => void;
type Pair = Comparison["pairs"][number];

export function ComparisonResults({
  dataset,
  comparison,
  onFilter,
  actionsRef,
}: {
  actionsRef: React.RefObject<ComparisonActions | null>;
  dataset: Dataset;
  comparison: Comparison;
  onFilter: InspectRows;
}) {
  const params = useSearchParams();
  const reference = comparison.reference ? comparison.columns.at(-1)! : null;
  const allPairs = params.get("pairs") === "all";
  const pairs = [...comparison.pairs]
    .filter((p) => !reference || allPairs || p.columns[1] === reference)
    .sort((a, b) =>
      a.numeric && b.numeric
        ? (a.numeric.mean_absolute_difference ?? Infinity) -
          (b.numeric.mean_absolute_difference ?? Infinity)
        : reference && !allPairs
          ? (b.rate ?? -1) - (a.rate ?? -1)
          : (a.rate ?? 2) - (b.rate ?? 2),
    );
  const pair = pairs.find((p) => JSON.stringify(p.columns) === params.get("pair")) ?? pairs[0];
  const ref = comparison.reference?.find(
    (r) => r.column === pair.columns[0] && pair.columns[1] === reference,
  );
  const requestedDetail = params.get("detail") ?? "differences";
  const detail =
    ["differences", "labels", "distribution", "coverage"].includes(requestedDetail) &&
    !(requestedDetail === "labels" && (!ref || pair.numeric))
      ? requestedDetail
      : "differences";
  const ruleLabel =
    comparison.tolerance !== null
      ? `tolerance ${comparison.tolerance}`
      : comparison.ignore_case || comparison.trim_whitespace
        ? "normalized match"
        : "exact match";
  function change(key: string, value: string) {
    const query = new URLSearchParams(window.location.search);
    query.set(key, value);
    window.history.replaceState(null, "", `/?${query}`);
  }
  const pairKey = JSON.stringify(pair.columns);
  useEffect(() => {
    if (
      params.get("pair") !== pairKey ||
      (params.has("detail") && params.get("detail") !== detail)
    ) {
      const query = new URLSearchParams(window.location.search);
      query.set("pair", pairKey);
      if (query.has("detail")) query.set("detail", detail);
      window.history.replaceState(null, "", `/?${query}`);
    }
  }, [pairKey, detail, params]);
  useEffect(() => {
    actionsRef.current?.setReady?.(true);
    return () => actionsRef.current?.setReady?.(false);
  }, [actionsRef]);
  useEffect(() => {
    actionsRef.current = {
      ...actionsRef.current,
      different: () => {
        if (pair.compared > pair.agree)
          onFilter(
            [
              {
                where: pair.disagree,
                label: `${pair.columns.join(" ≠ ")} · ${ruleLabel}`,
              },
            ],
            pair.columns,
          );
      },
    };
    return () => {
      actionsRef.current = { ...actionsRef.current, different: undefined };
    };
  }, [actionsRef, pair, ruleLabel, onFilter]);
  const missing = Object.values(pair.coverage).reduce((n, v) => n + v.rows, 0);
  return (
    <div className="flex min-h-0 flex-1 text-sm">
      {pairs.length > 1 && (
        <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar/30">
          <PaneHeader>
            <span className="font-medium">
              {pair.numeric
                ? "Absolute difference"
                : reference && !allPairs
                  ? "Against reference"
                  : "Column pairs"}
            </span>
          </PaneHeader>
          <div className="min-h-0 flex-1 overflow-auto p-2" aria-label="Comparisons">
            {pairs.map((p, i) => (
              <Button
                key={JSON.stringify(p.columns)}
                variant="ghost"
                className={`mb-1 h-auto w-full flex-col items-stretch gap-1.5 px-2 py-2 text-xs ${p === pair ? "bg-accent text-accent-foreground" : ""}`}
                aria-pressed={p === pair}
                onClick={() => change("pair", JSON.stringify(p.columns))}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault();
                    const next =
                      pairs[(i + (e.key === "ArrowDown" ? 1 : pairs.length - 1)) % pairs.length];
                    change("pair", JSON.stringify(next.columns));
                    const buttons = e.currentTarget.parentElement?.querySelectorAll("button");
                    (
                      buttons?.[
                        (i + (e.key === "ArrowDown" ? 1 : pairs.length - 1)) % pairs.length
                      ] as HTMLElement
                    )?.focus();
                  }
                }}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate">
                    {reference && !allPairs
                      ? columnLabel(p.columns[0])
                      : p.columns.map(columnLabel).join(" · ")}
                  </span>
                  <span className="tabular-nums">
                    {p.numeric
                      ? (p.numeric.mean_absolute_difference?.toLocaleString("en-US", {
                          maximumSignificantDigits: 3,
                        }) ?? "—")
                      : percent(p.rate)}
                  </span>
                </span>
                <Progress
                  value={
                    p.numeric
                      ? (100 * (p.numeric.mean_absolute_difference ?? 0)) /
                        Math.max(
                          ...pairs.map((v) => v.numeric?.mean_absolute_difference ?? 0),
                          Number.EPSILON,
                        )
                      : (p.rate ?? 0) * 100
                  }
                  aria-label={`${p.columns.join(" / ")} ${p.numeric ? "mean absolute difference" : "match rate"}`}
                  className="h-1"
                />
                <span className="text-left font-normal text-muted-foreground">
                  {p.numeric ? `Mean abs. difference · ${percent(p.rate)} match · ` : ""}
                  {formatNumber(p.compared - p.agree)} different ·{" "}
                  {formatNumber(comparison.rows - p.compared)} missing
                </span>
              </Button>
            ))}
          </div>
          {reference && (
            <div className="border-t p-2">
              <Button
                variant="ghost"
                size="sm"
                className="w-full text-xs"
                onClick={() => change("pairs", allPairs ? "reference" : "all")}
              >
                {allPairs ? "Against reference" : "Include model-to-model pairs"}
              </Button>
            </div>
          )}
        </aside>
      )}
      <Tabs
        className="flex min-h-0 min-w-0 flex-1 flex-col gap-0"
        value={
          ["differences", "labels", "distribution", "coverage"].includes(detail)
            ? detail
            : "differences"
        }
        onValueChange={(v) => change("detail", v)}
      >
        <PaneHeader>
          <span className="min-w-0 truncate font-medium" title={pair.columns.join(" → ")}>
            {pair.columns.map(columnLabel).join(" → ")}
          </span>
          <TabsList className="ml-auto shrink-0">
            <TabsTrigger value="differences">Differences</TabsTrigger>
            {ref && !pair.numeric && <TabsTrigger value="labels">Label metrics</TabsTrigger>}
            <TabsTrigger value="distribution">Values</TabsTrigger>
            <TabsTrigger value="coverage">Coverage{missing ? ` · ${missing}` : ""}</TabsTrigger>
          </TabsList>

          <TooltipButton
            label="Rates exclude missing answers. A reference is not necessarily ground truth. Select counts to inspect their rows."
            variant="ghost"
            size="icon-xs"
          >
            <InfoIcon />
          </TooltipButton>
        </PaneHeader>
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="max-w-5xl space-y-3 p-3">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 pb-1">
              <div>
                <span className="font-medium tabular-nums">
                  {pair.numeric
                    ? (pair.numeric.mean_absolute_difference?.toLocaleString("en-US", {
                        maximumSignificantDigits: 4,
                      }) ?? "—")
                    : percent(pair.rate)}
                </span>{" "}
                <span className="text-muted-foreground">
                  {pair.numeric
                    ? "mean absolute difference"
                    : comparison.tolerance !== null
                      ? "within tolerance"
                      : ref
                        ? "match reference"
                        : "agree"}
                </span>
              </div>
              <Count
                rows={pair.compared - pair.agree}
                where={pair.disagree}
                label={`${pair.columns.join(" ≠ ")} · ${ruleLabel}`}
                columns={pair.columns}
                onFilter={onFilter}
              >
                different
              </Count>
              <span className="ml-auto text-xs text-muted-foreground">
                {formatNumber(pair.compared)} / {formatNumber(comparison.rows)} paired
              </span>
            </div>
            <TabsContent value="differences" className="pt-2">
              {pair.numeric ? (
                <NumericComparison
                  pair={pair}
                  tolerance={comparison.tolerance}
                  onFilter={onFilter}
                />
              ) : (
                <PairDetail
                  dataset={dataset}
                  comparison={comparison}
                  pair={pair}
                  reference={ref ? reference : null}
                  onFilter={onFilter}
                />
              )}
            </TabsContent>
            <TabsContent value="labels" className="pt-2">
              {ref && <LabelMetrics reference={ref} />}
            </TabsContent>
            <TabsContent value="distribution" className="pt-2">
              <PairDetail
                dataset={dataset}
                comparison={comparison}
                pair={pair}
                reference={ref ? reference : null}
                onFilter={onFilter}
                distribution
              />
            </TabsContent>
            <TabsContent value="coverage" className="space-y-4 pt-4">
              <p className="text-xs text-muted-foreground">
                Rates use rows with both answers. Missing means NULL; an empty string is an answer.
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Answers missing</TableHead>
                    <TableHead className="text-right">Rows / inspect</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(pair.coverage).map(([key, value]) => (
                    <TableRow key={key}>
                      <TableCell>
                        {key === "missing_both"
                          ? "Both columns"
                          : columnLabel(pair.columns[key === "missing_left" ? 0 : 1])}
                      </TableCell>
                      <TableCell className="text-right">
                        <Count
                          rows={value.rows}
                          where={value.where}
                          label={key.replaceAll("_", " ")}
                          columns={pair.columns}
                          onFilter={onFilter}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {pair.numeric && (
                <p className="text-xs text-muted-foreground">
                  Numeric diagnostics use {pair.numeric.finite_pairs} finite pairs;{" "}
                  {pair.numeric.non_finite_pairs} non-finite pairs excluded.
                </p>
              )}
            </TabsContent>
          </div>
        </div>
      </Tabs>
    </div>
  );
}

function PairDetail({
  dataset,
  comparison,
  pair,
  reference,
  onFilter,
  distribution = false,
}: {
  dataset: Dataset;
  comparison: Comparison;
  pair: Pair;
  reference: string | null;
  onFilter: InspectRows;
  distribution?: boolean;
}) {
  const request = useMemo(
    () =>
      comparison.columns.length === 2
        ? undefined
        : {
            sql: ALL_ROWS,
            columns: pair.columns,
            reference: null,
            tolerance: comparison.tolerance,
            ignore_case: comparison.ignore_case,
            trim_whitespace: comparison.trim_whitespace,
          },
    [
      comparison.columns.length,
      pair.columns,
      comparison.tolerance,
      comparison.ignore_case,
      comparison.trim_whitespace,
    ],
  );
  const result = useComparison(dataset.id, request, dataset.run?.done);
  const data = comparison.columns.length === 2 ? comparison : result.data;
  if (result.error)
    return (
      <Alert variant="destructive">
        <AlertDescription>{result.error}</AlertDescription>
        <Button size="sm" variant="outline" onClick={result.retry}>
          Retry pair
        </Button>
      </Alert>
    );
  if (!data)
    return (
      <div role="status" className="flex items-center gap-2 text-muted-foreground">
        <Spinner />
        Loading pair…
      </div>
    );
  return distribution ? (
    <Distributions comparison={data} dataset={dataset} onFilter={onFilter} />
  ) : (
    <Crosstab
      comparison={data}
      pair={pair}
      tolerance={comparison.tolerance}
      reference={reference}
      onFilter={onFilter}
    />
  );
}

function LabelMetrics({ reference }: { reference: NonNullable<Comparison["reference"]>[number] }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-6 text-xs">
        <span className="inline-flex items-center gap-1">
          Macro F1 <strong>{percent(reference.macro_f1)}</strong>
        </span>
        <span className="inline-flex items-center gap-1">
          Balanced accuracy <strong>{percent(reference.balanced_accuracy)}</strong>
        </span>
        <TooltipButton
          label="Precision: correct predictions / predicted. Recall: correct / reference support. Macro F1 averages per-label F1; balanced accuracy averages recall. Missing pairs are excluded."
          variant="ghost"
          size="icon-xs"
        >
          <InfoIcon />
        </TooltipButton>
      </div>
      <Table className="max-w-2xl table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-44">Reference label</TableHead>
            <TableHead className="text-right">Precision</TableHead>
            <TableHead className="text-right">Recall</TableHead>
            <TableHead className="text-right">Support</TableHead>
            <TableHead className="text-right">Predicted</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {reference.values.map((v) => (
            <TableRow key={v.value}>
              <TableCell>{v.value || '""'}</TableCell>
              <TableCell className="text-right tabular-nums">{percent(v.precision)}</TableCell>
              <TableCell className="text-right tabular-nums">{percent(v.recall)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(v.support)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(v.predicted)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">
        Lowest recall first · {reference.labels_completeness.shown_groups} of{" "}
        {reference.labels_completeness.total_groups} reference labels. Aggregate metrics use all
        labels.
      </p>
    </section>
  );
}

function Crosstab({
  comparison,
  pair,
  tolerance,
  reference,
  onFilter,
}: {
  comparison: Comparison;
  pair: Pair;
  tolerance: number | null;
  reference: string | null;
  onFilter: InspectRows;
}) {
  const cells = comparison.crosstab ?? [];
  const [a, b] = pair.columns;
  const across = [...new Set(cells.map((c) => c.values[1]))].sort();
  const down = [...new Set(cells.map((c) => c.values[0]))].sort();
  const cellMap = new Map(cells.map((c) => [JSON.stringify(c.values), c]));
  const represented = cells.reduce((sum, c) => sum + c.rows, 0);
  const complete = !comparison.crosstab_completeness?.truncated;
  const maxError = Math.max(
    1,
    ...cells.filter((c) => c.values[0] !== c.values[1]).map((c) => c.rows),
  );
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="font-medium">{reference ? "Confusion table" : "Value combinations"}</h3>
        <span className="text-xs text-muted-foreground">
          {reference ? "Prediction ↓ · Reference →" : `${columnLabel(a)} ↓ · ${columnLabel(b)} →`}
        </span>
        <TooltipButton
          label="Accent highlights differences; stronger tint means more rows. Matches stay quiet. Select a count to inspect its rows."
          variant="ghost"
          size="icon-xs"
        >
          <InfoIcon />
        </TooltipButton>
      </div>
      {(comparison.ignore_case || comparison.trim_whitespace) && (
        <p className="text-xs text-muted-foreground">
          Normalized labels · {comparison.ignore_case ? "ignore case" : ""}
          {comparison.ignore_case && comparison.trim_whitespace ? " + " : ""}
          {comparison.trim_whitespace ? "trim whitespace" : ""}. Source values stay unchanged.
        </p>
      )}
      {tolerance !== null && (
        <p className="text-xs text-muted-foreground">
          Raw value combinations; tint shows frequency, not tolerance agreement. The agreement rate
          above uses the active tolerance.
        </p>
      )}
      {!cells.length ? (
        <p className="py-3 text-muted-foreground">No rows have answers in both columns.</p>
      ) : (
        <Table className="table-fixed" style={{ width: 144 + 88 * (across.length + 1) }}>
          <TableHeader>
            <TableRow>
              <TableHead className="w-36 truncate" title={columnLabel(a)}>
                {reference ? "Prediction" : columnLabel(a)}
              </TableHead>
              {across.map((v) => (
                <TableHead key={v} className="w-22 truncate text-right" title={v}>
                  {v || '""'}
                </TableHead>
              ))}
              <TableHead className="text-right">{complete ? "Total" : "Shown total"}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {down.map((row) => (
              <TableRow key={row}>
                <TableCell className="max-w-40 truncate font-medium" title={row}>
                  {row || '""'}
                </TableCell>
                {across.map((col) => {
                  const c = cellMap.get(JSON.stringify([row, col]));
                  return (
                    <TableCell key={col} className="p-1 text-right">
                      {c ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="w-full justify-end gap-1 text-xs tabular-nums"
                          style={{
                            backgroundColor: `color-mix(in oklch, ${row === col ? "var(--muted-foreground)" : "var(--primary)"} ${row === col ? 5 : 22 + (23 * c.rows) / maxError}%, transparent)`,
                          }}
                          aria-label={`${columnLabel(a)}: ${row}; ${columnLabel(b)}: ${col}; ${formatNumber(c.rows)} rows`}
                          onClick={() =>
                            onFilter(
                              [
                                {
                                  where: c.where,
                                  label: `${columnLabel(a)} matches ${row}, ${columnLabel(b)} matches ${col}`,
                                },
                              ],
                              pair.columns,
                            )
                          }
                        >
                          {formatNumber(c.rows)}
                        </Button>
                      ) : (
                        <span
                          className="px-2 text-muted-foreground/40"
                          aria-label={complete ? "0 rows" : "Not shown"}
                        >
                          {complete ? "·" : "—"}
                        </span>
                      )}
                    </TableCell>
                  );
                })}
                <TableCell className="text-right tabular-nums">
                  {formatNumber(
                    cells.filter((c) => c.values[0] === row).reduce((n, c) => n + c.rows, 0),
                  )}
                </TableCell>
              </TableRow>
            ))}
            <TableRow className="font-medium">
              <TableCell>{complete ? "Total" : "Shown total"}</TableCell>
              {across.map((value) => (
                <TableCell key={value} className="text-right tabular-nums">
                  {formatNumber(
                    cells.filter((c) => c.values[1] === value).reduce((n, c) => n + c.rows, 0),
                  )}
                </TableCell>
              ))}
              <TableCell className="text-right tabular-nums">{formatNumber(represented)}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      )}
      <p className="text-xs text-muted-foreground">
        Showing {formatNumber(represented)} of {formatNumber(pair.compared)} paired rows.
        {!complete && " Some combinations are omitted; — means not shown, not necessarily zero."}
        {comparison.crosstab_completeness?.truncated &&
          ` ${comparison.crosstab_completeness.shown_groups} of ${comparison.crosstab_completeness.total_groups} combinations shown.`}
      </p>
    </section>
  );
}

function Distributions({
  comparison,
  dataset,
  onFilter,
}: {
  comparison: Comparison;
  dataset: Dataset;
  onFilter: InspectRows;
}) {
  const numeric = comparison.columns.every((name) =>
    /^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|FLOAT|DOUBLE|DECIMAL.*)$/.test(
      dataset.columns.find((c) => c.name === name)?.type ?? "",
    ),
  );
  const values = numeric
    ? [...comparison.values].sort((a, b) =>
        a.value === null ? 1 : b.value === null ? -1 : Number(a.value) - Number(b.value),
      )
    : comparison.values;
  return (
    <>
      <h3 className="font-medium">How often each value is used</h3>
      <p className="text-xs text-muted-foreground">
        All {formatNumber(comparison.rows)} rows · {comparison.values_completeness.shown_groups} of{" "}
        {comparison.values_completeness.total_groups} values shown. “Other values” combines the
        rest. Missing answers are separate.
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Value</TableHead>
            {comparison.columns.map((c) => (
              <TableHead key={c} className="min-w-32 max-w-48 truncate" title={c}>
                {columnLabel(c)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {values.map((v) => (
            <TableRow key={JSON.stringify(v.value)}>
              <TableCell className="max-w-40 truncate" title={v.value ?? "Other values"}>
                {v.value === null ? "Other values" : v.value || '""'}
              </TableCell>
              {comparison.columns.map((c) => (
                <TableCell key={c}>
                  <div className="mb-1 text-xs tabular-nums">
                    <Count
                      rows={v.counts[c] ?? 0}
                      where={v.where[c]}
                      label={`${columnLabel(c)}: ${v.value ?? "Other values"}`}
                      columns={[c]}
                      onFilter={onFilter}
                    />
                  </div>
                  <Progress
                    value={comparison.rows ? (100 * (v.counts[c] ?? 0)) / comparison.rows : 0}
                    aria-label={`${columnLabel(c)}: ${v.value ?? "Other values"}`}
                  />
                </TableCell>
              ))}
            </TableRow>
          ))}
          <TableRow>
            <TableCell className="text-muted-foreground">Missing answer</TableCell>
            {comparison.columns.map((c) => (
              <TableCell key={c} className="tabular-nums text-muted-foreground">
                <Count
                  rows={
                    comparison.rows - comparison.values.reduce((n, v) => n + (v.counts[c] ?? 0), 0)
                  }
                  where={`${ident(c)} IS NULL`}
                  label={`Missing ${columnLabel(c)}`}
                  columns={[c]}
                  onFilter={onFilter}
                />
              </TableCell>
            ))}
          </TableRow>
        </TableBody>
      </Table>
    </>
  );
}

function Count({
  rows,
  where,
  label,
  columns,
  onFilter,
  children,
}: {
  rows: number;
  where?: string | null;
  label: string;
  columns: string[];
  onFilter: InspectRows;
  children?: React.ReactNode;
}) {
  return where && rows > 0 ? (
    <Button
      variant="ghost"
      size="sm"
      className="h-auto px-0 text-xs text-primary hover:text-primary dark:hover:text-primary tabular-nums"
      aria-label={`Inspect ${formatNumber(rows)} rows: ${label}`}
      title={children === "different" ? "Inspect different rows (⌘↵)" : undefined}
      onClick={() => onFilter([{ where, label }], columns)}
    >
      {formatNumber(rows)}
      {children && <> {children}</>}
    </Button>
  ) : (
    <span className="tabular-nums">
      {formatNumber(rows)}
      {children && <> {children}</>}
    </span>
  );
}

function percent(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;
}
