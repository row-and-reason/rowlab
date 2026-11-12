"use client";

import { Count, Definition } from "@/components/comparison-parts";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { columnLabel } from "@/lib/format";
import { metric, missingRows, percent, type InspectRows, type Pair } from "@/lib/comparison";

/** The summary table: one row per pair, arrow keys move the selection. */
export function ComparisonPairs({
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
        {pairs.map((p, i) => (
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
                  const next = (i + (e.key === "ArrowDown" ? 1 : pairs.length - 1)) % pairs.length;
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
                rows={missingRows(p)}
                where={Object.values(p.coverage)
                  .map((v) => `(${v.where})`)
                  .join(" OR ")}
                label={`Missing answers: ${p.columns.join(" / ")}`}
                columns={p.columns}
                onFilter={onFilter}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
