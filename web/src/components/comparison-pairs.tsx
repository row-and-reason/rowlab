"use client";

import { Count, Definition, Rate } from "@/components/comparison-parts";
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
import { type Comparison } from "@/lib/api/client";
import { columnLabel } from "@/lib/format";
import {
  againstReference,
  metric,
  missingRows,
  usd,
  type InspectRows,
  type Pair,
} from "@/lib/comparison";

/**
 * The summary table: one row per pair, arrow keys move the selection. Models against the reference
 * also get their calibration and cost, when any of them has some.
 */
export function ComparisonPairs({
  comparison,
  pairs,
  selected,
  reference,
  tolerance,
  onSelect,
  onFilter,
}: {
  comparison: Comparison;
  pairs: Pair[];
  selected: Pair;
  reference: string | null;
  tolerance: number | null;
  onSelect: (pair: Pair) => void;
  onFilter: InspectRows;
}) {
  const numeric = pairs.every((p) => p.numeric);
  const rows = pairs.map((p) => ({ p, ...againstReference(comparison, p) }));
  const calibrated = rows.some((r) => r.metrics?.calibration);
  const costed = rows.some((r) => r.cost);
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
          {!numeric && (
            <TableHead className="text-right">
              <Definition
                label="κ"
                description="Cohen's κ: agreement beyond chance; 1 is perfect, 0 is chance."
              />
            </TableHead>
          )}
          {calibrated && (
            <>
              <TableHead className="text-right">
                <Definition
                  label="Brier"
                  description="Mean squared gap between the probability and being right; 0 is perfect."
                />
              </TableHead>
              <TableHead className="text-right">
                <Definition
                  label="ECE"
                  description="How far the probability is from the accuracy, over ten bins; 0 is perfect."
                />
              </TableHead>
              <TableHead className="text-right">
                <Definition
                  label="AUROC"
                  description="How well the probability tells right answers from wrong; 1 is perfect, 0.5 is chance."
                />
              </TableHead>
            </>
          )}
          {costed && (
            <>
              <TableHead className="text-right">
                <Definition
                  label="$/1k rows"
                  description="What the run spent on this model, per 1,000 answered rows. Cached answers are free."
                />
              </TableHead>
              <TableHead className="text-right">
                <Definition
                  label="$/correct"
                  description="Cost per answered row divided by the accuracy."
                />
              </TableHead>
            </>
          )}
          <TableHead className="text-right">Different</TableHead>
          <TableHead className="text-right">Missing</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(({ p, metrics, cost }, i) => (
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
                <Rate rate={p.rate} ci={p.rate_ci} />
              </div>
            </TableCell>
            {!numeric && (
              <TableCell className="text-right text-xs tabular-nums">{metric(p.kappa)}</TableCell>
            )}
            {calibrated && (
              <>
                <TableCell className="text-right text-xs tabular-nums">
                  {metric(metrics?.calibration?.brier ?? null)}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {metric(metrics?.calibration?.ece ?? null)}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {metric(metrics?.calibration?.auroc ?? null)}
                </TableCell>
              </>
            )}
            {costed && (
              <>
                <TableCell className="text-right text-xs tabular-nums">
                  {usd(cost?.usd_per_1k_rows ?? null)}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {usd(metrics?.usd_per_correct ?? null)}
                </TableCell>
              </>
            )}
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
