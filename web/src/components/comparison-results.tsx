"use client";

import { ChevronDownIcon } from "lucide-react";
import { useMemo, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { ComparisonCrosstab } from "@/components/comparison-crosstab";
import { ComparisonPairs } from "@/components/comparison-pairs";
import { Count, Definition, Rate } from "@/components/comparison-parts";
import { NumericComparison } from "@/components/numeric-comparison";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type Comparison, type Dataset } from "@/lib/api/client";
import {
  againstReference,
  metric,
  missingRows,
  percent,
  type InspectRows,
  type Pair,
  type ReferenceMetrics,
} from "@/lib/comparison";
import { columnLabel, formatNumber } from "@/lib/format";
import { ALL_ROWS } from "@/lib/sql";
import { useComparison, type ComparisonActions } from "@/lib/use-comparison";

export function ComparisonResults({
  dataset,
  version,
  comparison,
  onFilter,
  actionsRef,
}: {
  actionsRef: React.RefObject<ComparisonActions | null>;
  dataset: Dataset;
  /** Changes when answers do, so a pair's own comparison is fetched again. */
  version: number;
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
  const ref = againstReference(comparison, pair).metrics;
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
  const missing = missingRows(pair);
  return (
    <div className="min-h-0 flex-1 overflow-auto text-sm">
      <div className="space-y-4 p-3">
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums">
          {comparison.columns.length > 2 && (
            <span>
              <Definition
                label="All agree"
                description="Rows where every answer is the same / those rows plus rows where at least two answers differ. Rows with some answers missing and the rest the same are left out."
              />{" "}
              <strong>
                <Rate rate={comparison.agreement.rate} ci={comparison.agreement.rate_ci} />
              </strong>
            </span>
          )}
          <span>
            <Definition
              label="α"
              description="Krippendorff's α across all columns: agreement beyond chance; 1 is perfect, 0 is chance."
            />{" "}
            <strong>{metric(comparison.agreement.alpha)}</strong>{" "}
            <span className="text-muted-foreground">{comparison.agreement.alpha_level}</span>
          </span>
        </div>
        <ComparisonPairs
          comparison={comparison}
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
              <ComparisonPairs
          comparison={comparison}
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
            {ref?.calibration && (
              <span>
                <Definition
                  label="Calibrated on"
                  description="Rows with an answer, a reference and a probability between 0 and 1."
                />{" "}
                <strong>{formatNumber(ref.calibration.rows)}</strong>{" "}
                <span className="text-muted-foreground">
                  {columnLabel(ref.calibration.probability_column)}
                </span>
              </span>
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
        {ref?.calibration && ref.calibration.bins.length > 0 && (
          <Calibration calibration={ref.calibration} columns={pair.columns} onFilter={onFilter} />
        )}
        {pair.numeric ? (
          <NumericComparison pair={pair} tolerance={comparison.tolerance} onFilter={onFilter} />
        ) : (
          <PairDetail
            dataset={dataset}
            version={version}
            comparison={comparison}
            pair={pair}
            reference={ref ? reference : null}
            metrics={ref}
            onFilter={onFilter}
          />
        )}
      </div>
    </div>
  );
}

function PairDetail({
  dataset,
  version,
  comparison,
  pair,
  reference,
  metrics,
  onFilter,
}: {
  dataset: Dataset;
  version: number;
  comparison: Comparison;
  pair: Pair;
  reference: string | null;
  metrics: ReferenceMetrics | undefined;
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
  const result = useComparison(dataset.id, request, version);
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
    <ComparisonCrosstab
      comparison={data}
      pair={pair}
      tolerance={comparison.tolerance}
      reference={reference}
      metrics={metrics}
      onFilter={onFilter}
    />
  );
}

/** The model's probability in ten bins, each with how often it is right; a bin's rows open in Rows. */
function Calibration({
  calibration,
  columns,
  onFilter,
}: {
  calibration: NonNullable<ReferenceMetrics["calibration"]>;
  columns: string[];
  onFilter: InspectRows;
}) {
  const probability = columnLabel(calibration.probability_column);
  return (
    <section className="space-y-2">
      <h3 className="font-medium">Calibration</h3>
      <Table aria-label="Calibration bins">
        <TableHeader>
          <TableRow>
            <TableHead>{probability}</TableHead>
            <TableHead className="text-right">Rows</TableHead>
            <TableHead className="text-right">
              <Definition label="Mean probability" description="The bin's average probability." />
            </TableHead>
            <TableHead className="text-right">
              <Definition label="Accuracy" description="The share of the bin's rows that are right." />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {calibration.bins.map((bin) => {
            const range = `${bin.lower.toFixed(1)}–${bin.upper.toFixed(1)}`;
            return (
              <TableRow key={bin.lower}>
                <TableCell className="text-xs tabular-nums">{range}</TableCell>
                <TableCell className="text-right">
                  <Count
                    rows={bin.rows}
                    where={bin.where}
                    label={`${probability} in ${range}`}
                    columns={[...columns, calibration.probability_column]}
                    onFilter={onFilter}
                  />
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {percent(bin.mean_probability)}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {percent(bin.accuracy)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </section>
  );
}
