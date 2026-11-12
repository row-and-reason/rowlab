"use client";

import { Definition } from "@/components/comparison-parts";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type Comparison } from "@/lib/api/client";
import {
  crosstabMatrix,
  percent,
  type InspectRows,
  type Pair,
  type ReferenceMetrics,
} from "@/lib/comparison";
import { columnLabel, formatNumber } from "@/lib/format";

/** Value combinations of one pair; with a reference it is a confusion table with precision and recall. */
export function ComparisonCrosstab({
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
  metrics?: ReferenceMetrics;
  onFilter: InspectRows;
}) {
  const [a, b] = pair.columns;
  const matrix = crosstabMatrix(comparison, metrics);
  const { across, complete } = matrix;
  const completeness = comparison.crosstab_completeness;
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
      {!matrix.cells.length ? (
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
            {matrix.down.map((row) => (
              <TableRow key={row}>
                <TableCell className="max-w-40 truncate font-medium" title={row}>
                  {row || '""'}
                </TableCell>
                {across.map((col) => {
                  const c = matrix.cell(row, col);
                  return (
                    <TableCell key={col} className="p-1 text-right">
                      {c ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="w-full justify-end gap-1 text-xs tabular-nums"
                          style={{
                            backgroundColor: `color-mix(in oklch, ${row === col ? "var(--muted-foreground)" : "var(--primary)"} ${row === col ? 5 : 22 + (23 * c.rows) / matrix.maxError}%, transparent)`,
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
                  {formatNumber(matrix.rowTotal(row))}
                </TableCell>
                {reference && (
                  <TableCell className="text-right tabular-nums">
                    {percent(matrix.precision(row))}
                  </TableCell>
                )}
              </TableRow>
            ))}
            <TableRow className="font-medium">
              <TableCell>{complete ? "Total" : "Shown total"}</TableCell>
              {across.map((value) => (
                <TableCell key={value} className="text-right tabular-nums">
                  {formatNumber(matrix.columnTotal(value))}
                </TableCell>
              ))}
              <TableCell className="text-right tabular-nums">
                {formatNumber(matrix.represented)}
              </TableCell>
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
                    {percent(matrix.recall(value))}
                  </TableCell>
                ))}
                <TableCell />
                <TableCell />
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
      {completeness?.truncated && (
        <p className="text-xs text-muted-foreground">
          Showing {formatNumber(matrix.represented)} of {formatNumber(pair.compared)} paired rows.
          {" Some combinations are omitted; — means not shown, not necessarily zero."}
          {` ${completeness.shown_groups} of ${completeness.total_groups} combinations shown.`}
        </p>
      )}
    </section>
  );
}
