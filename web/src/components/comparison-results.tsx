"use client";

import { ChevronDownIcon } from "lucide-react";
import { useMemo, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { NumericComparison } from "@/components/numeric-comparison";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type Comparison, type Dataset } from "@/lib/api/client";
import { columnLabel, formatNumber } from "@/lib/format";
import { ALL_ROWS, type WhereFilter } from "@/lib/sql";
import { useComparison, type ComparisonActions } from "@/lib/use-comparison";

type InspectRows = (filters: WhereFilter[], columns: string[]) => void;
type Pair = Comparison["pairs"][number];
const metric = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("en-US", { maximumSignificantDigits: 4 });

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
  const pairs = [...comparison.pairs].sort((a, b) =>
    a.numeric && b.numeric
      ? (a.numeric.mean_absolute_difference ?? Infinity) -
        (b.numeric.mean_absolute_difference ?? Infinity)
      : reference
        ? (b.rate ?? -1) - (a.rate ?? -1)
        : (a.rate ?? 2) - (b.rate ?? 2),
  );
  const primary = pairs.filter((p) => !reference || p.columns[1] === reference);
  const secondary = reference ? pairs.filter((p) => p.columns[1] !== reference) : [];
  const pair = pairs.find((p) => JSON.stringify(p.columns) === params.get("pair")) ?? primary[0];
  const ref = comparison.reference?.find(
    (r) => r.column === pair.columns[0] && pair.columns[1] === reference,
  );
  const ruleLabel =
    comparison.tolerance !== null
      ? `tolerance ${comparison.tolerance}`
      : comparison.ignore_case || comparison.trim_whitespace
        ? "normalized match"
        : "exact match";
  const pairKey = JSON.stringify(pair.columns);
  function select(p: Pair) {
    const query = new URLSearchParams(window.location.search);
    query.set("pair", JSON.stringify(p.columns));
    window.history.replaceState(null, "", `/?${query}`);
  }
  useEffect(() => {
    if (
      params.get("pair") !== pairKey ||
      ["detail", "pairs", "focus"].some((key) => params.has(key))
    ) {
      const query = new URLSearchParams(window.location.search);
      query.set("pair", pairKey);
      for (const key of ["detail", "pairs", "focus"]) query.delete(key);
      window.history.replaceState(null, "", `/?${query}`);
    }
  }, [pairKey, params]);
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
            [{ where: pair.disagree, label: `${pair.columns.join(" ≠ ")} · ${ruleLabel}` }],
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
    <div className="min-h-0 flex-1 overflow-auto text-sm">
      <div className="space-y-4 p-3">
        <PairTable
          pairs={primary}
          selected={pair}
          reference={reference}
          tolerance={comparison.tolerance}
          onSelect={select}
          onFilter={onFilter}
        />
        {secondary.length > 0 && (
          <Collapsible key={reference} defaultOpen={secondary.includes(pair)}>
            <CollapsibleTrigger
              render={<Button variant="ghost" size="sm" className="px-0 text-xs" />}
            >
              <ChevronDownIcon className="size-3" /> Between models · {secondary.length} pairs
            </CollapsibleTrigger>
            <CollapsibleContent>
              <PairTable
                pairs={secondary}
                selected={pair}
                reference={null}
                tolerance={comparison.tolerance}
                onSelect={select}
                onFilter={onFilter}
              />
            </CollapsibleContent>
          </Collapsible>
        )}
        <section className="space-y-2 border-t pt-3" aria-label="Selected comparison">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <h3 className="font-medium">{pair.columns.map(columnLabel).join(" → ")}</h3>
            <span className="ml-auto text-xs text-muted-foreground tabular-nums">
              <Definition
                label={`${formatNumber(pair.compared)} / ${formatNumber(comparison.rows)} paired`}
                description="Rows with both answers / all dataset rows. Missing means NULL, not an empty string. Matrix totals and rates use paired rows."
              />
            </span>
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
            {pair.numeric ? (
              <>
                <span>
                  <Definition
                    label="P95"
                    description="95th percentile of absolute differences among finite pairs."
                  />{" "}
                  <strong>{metric(pair.numeric.p95_absolute_difference)}</strong>
                </span>
                <span>
                  Max <strong>{metric(pair.numeric.max_absolute_difference)}</strong>
                </span>
                {pair.numeric.non_finite_pairs > 0 && (
                  <span className="text-muted-foreground">
                    {pair.numeric.non_finite_pairs} non-finite pairs excluded
                  </span>
                )}
              </>
            ) : (
              ref && (
                <>
                  <span>
                    <Definition
                      label="Macro F1"
                      description="Mean per-label F1 across all labels; missing pairs excluded."
                    />{" "}
                    <strong>{percent(ref.macro_f1)}</strong>
                  </span>
                  <span>
                    <Definition
                      label="Balanced accuracy"
                      description="Mean recall across all reference labels; the reference is not necessarily ground truth."
                    />{" "}
                    <strong>{percent(ref.balanced_accuracy)}</strong>
                  </span>
                </>
              )
            )}
          </div>
          {missing > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{formatNumber(missing)} missing:</span>
              {Object.entries(pair.coverage)
                .filter(([, v]) => v.rows > 0)
                .map(([key, value]) => {
                  const label =
                    key === "missing_both"
                      ? "both empty"
                      : `${columnLabel(pair.columns[key === "missing_left" ? 0 : 1])} empty`;
                  return (
                    <Count
                      key={key}
                      rows={value.rows}
                      where={value.where}
                      label={label}
                      columns={pair.columns}
                      onFilter={onFilter}
                    >
                      {label}
                    </Count>
                  );
                })}
            </div>
          )}
        </section>
        {pair.numeric ? (
          <NumericComparison pair={pair} tolerance={comparison.tolerance} onFilter={onFilter} />
        ) : (
          <PairDetail
            dataset={dataset}
            comparison={comparison}
            pair={pair}
            reference={ref ? reference : null}
            onFilter={onFilter}
          />
        )}
      </div>
    </div>
  );
}

function PairTable({
  pairs,
  selected,
  reference,
  tolerance,
  onSelect,
  onFilter,
}: {
  pairs: Pair[];
  selected: Pair;
  reference: string | null;
  tolerance: number | null;
  onSelect: (pair: Pair) => void;
  onFilter: InspectRows;
}) {
  const numeric = pairs.every((p) => p.numeric);
  return (
    <Table aria-label={reference ? "Models against reference" : "Column pairs"}>
      <TableHeader>
        <TableRow>
          <TableHead>{reference ? "Model" : "Pair"}</TableHead>
          {numeric && (
            <>
              <TableHead className="text-right">
                <Definition
                  label="Mean abs. Δ"
                  description="Mean absolute difference among finite paired answers."
                />
              </TableHead>
              <TableHead className="text-right">
                <Definition
                  label="Bias"
                  description="Signed mean difference. The chart names the subtraction direction."
                />
              </TableHead>
            </>
          )}
          <TableHead className="text-right">
            <Definition
              label={tolerance !== null ? "Within tolerance" : "Match"}
              description="Matching answers / paired answers. Missing answers are excluded."
            />
          </TableHead>
          <TableHead className="text-right">Different</TableHead>
          <TableHead className="text-right">Missing</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {pairs.map((p, i) => {
          const missing = Object.values(p.coverage).reduce((n, v) => n + v.rows, 0);
          return (
            <TableRow
              key={JSON.stringify(p.columns)}
              data-state={p === selected ? "selected" : undefined}
            >
              <TableCell className="py-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-auto max-w-52 justify-start px-0 text-xs"
                  aria-pressed={p === selected}
                  data-pair-selector
                  onClick={() => onSelect(p)}
                  onKeyDown={(e) => {
                    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
                    e.preventDefault();
                    const next =
                      (i + (e.key === "ArrowDown" ? 1 : pairs.length - 1)) % pairs.length;
                    onSelect(pairs[next]);
                    e.currentTarget
                      .closest("tbody")
                      ?.querySelectorAll<HTMLButtonElement>("[data-pair-selector]")
                      [next]?.focus();
                  }}
                >
                  <span className="truncate" title={p.columns.join(" → ")}>
                    {reference ? columnLabel(p.columns[0]) : p.columns.map(columnLabel).join(" → ")}
                  </span>
                </Button>
              </TableCell>
              {numeric && (
                <>
                  <TableCell className="text-right text-xs tabular-nums">
                    {metric(p.numeric!.mean_absolute_difference)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {metric(p.numeric!.bias)}
                  </TableCell>
                </>
              )}
              <TableCell className="text-right text-xs tabular-nums">
                <div className="flex items-center justify-end gap-2">
                  {!numeric && (
                    <Progress
                      className="h-1 w-16"
                      value={(p.rate ?? 0) * 100}
                      aria-label={`${p.columns.join(" / ")} match rate`}
                    />
                  )}
                  {percent(p.rate)}
                </div>
              </TableCell>
              <TableCell className="text-right">
                <Count
                  rows={p.compared - p.agree}
                  where={p.disagree}
                  label={`${p.columns.join(" ≠ ")}`}
                  columns={p.columns}
                  onFilter={onFilter}
                />
              </TableCell>
              <TableCell className="text-right">
                <Count
                  rows={missing}
                  where={Object.values(p.coverage)
                    .map((v) => `(${v.where})`)
                    .join(" OR ")}
                  label={`Missing answers: ${p.columns.join(" / ")}`}
                  columns={p.columns}
                  onFilter={onFilter}
                />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function Definition({ label, description }: { label: string; description: string }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="cursor-help" />}>
        {label}
      </TooltipTrigger>
      <TooltipContent>{description}</TooltipContent>
    </Tooltip>
  );
}

function PairDetail({
  dataset,
  comparison,
  pair,
  reference,
  onFilter,
}: {
  dataset: Dataset;
  comparison: Comparison;
  pair: Pair;
  reference: string | null;
  onFilter: InspectRows;
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
  return (
    <Crosstab
      comparison={data}
      pair={pair}
      tolerance={comparison.tolerance}
      reference={reference}
      metrics={comparison.reference?.find((r) => r.column === pair.columns[0])}
      onFilter={onFilter}
    />
  );
}

function Crosstab({
  comparison,
  pair,
  tolerance,
  reference,
  metrics,
  onFilter,
}: {
  comparison: Comparison;
  pair: Pair;
  tolerance: number | null;
  reference: string | null;
  metrics?: NonNullable<Comparison["reference"]>[number];
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
        <Table
          className="table-fixed"
          style={{ width: "100%", minWidth: 112 + 76 * (across.length + (reference ? 2 : 1)) }}
        >
          <TableHeader>
            <TableRow>
              <TableHead className="w-28 truncate" title={columnLabel(a)}>
                {reference ? "Prediction" : columnLabel(a)}
              </TableHead>
              {across.map((v) => (
                <TableHead key={v} className="truncate text-right" title={v}>
                  {v || '""'}
                </TableHead>
              ))}
              <TableHead className="text-right">
                <Definition
                  label={complete ? "Total" : "Shown"}
                  description="Paired rows only; missing answers are excluded."
                />
              </TableHead>
              {reference && (
                <TableHead className="text-right">
                  <Definition
                    label="Precision"
                    description="Correct predictions divided by all predictions of this label, among paired rows."
                  />
                </TableHead>
              )}
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
                {reference && (
                  <TableCell className="text-right tabular-nums">
                    {percent(
                      complete
                        ? (cellMap.get(JSON.stringify([row, row]))?.rows ?? 0) /
                            cells.filter((c) => c.values[0] === row).reduce((n, c) => n + c.rows, 0)
                        : (metrics?.values.find((v) => v.value === row)?.precision ?? null),
                    )}
                  </TableCell>
                )}
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
              {reference && <TableCell />}
            </TableRow>
            {reference && (
              <TableRow>
                <TableCell>
                  <Definition
                    label="Recall"
                    description="Correct predictions divided by reference support for this label, among paired rows."
                  />
                </TableCell>
                {across.map((value) => (
                  <TableCell key={value} className="text-right tabular-nums">
                    {percent(
                      complete
                        ? (cellMap.get(JSON.stringify([value, value]))?.rows ?? 0) /
                            cells
                              .filter((c) => c.values[1] === value)
                              .reduce((n, c) => n + c.rows, 0)
                        : (metrics?.values.find((v) => v.value === value)?.recall ?? null),
                    )}
                  </TableCell>
                ))}
                <TableCell />
                <TableCell />
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
      {!complete && (
        <p className="text-xs text-muted-foreground">
          Showing {formatNumber(represented)} of {formatNumber(pair.compared)} paired rows.
          {!complete && " Some combinations are omitted; — means not shown, not necessarily zero."}
          {comparison.crosstab_completeness?.truncated &&
            ` ${comparison.crosstab_completeness.shown_groups} of ${comparison.crosstab_completeness.total_groups} combinations shown.`}
        </p>
      )}
    </section>
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
