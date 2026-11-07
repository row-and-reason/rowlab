"use client";

import { ArrowRightIcon, CheckIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { NumericComparison } from "@/components/numeric-comparison";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { type Comparison, type Dataset } from "@/lib/api/client";
import { columnLabel, formatNumber } from "@/lib/format";
import { ALL_ROWS, ident, type WhereFilter } from "@/lib/sql";
import { useComparison } from "@/lib/use-comparison";

type InspectRows = (filters: WhereFilter[], columns: string[]) => void;
type Pair = Comparison["pairs"][number];

export function ComparisonResults({
  dataset,
  comparison,
  tolerance,
  onFilter,
}: {
  dataset: Dataset;
  comparison: Comparison;
  tolerance: number | null | undefined;
  onFilter: InspectRows;
}) {
  const [view, setView] = useState("overview");
  const ref = comparison.reference ? comparison.columns.at(-1)! : null;
  const pairs = comparison.pairs;
  const initialPair = pairs.find((p) => p.columns[1] === ref) ?? pairs[0];
  const [pairKey, setPairKey] = useState(JSON.stringify(initialPair.columns));
  const pair = pairs.find((p) => JSON.stringify(p.columns) === pairKey) ?? initialPair;
  const { agreement, columns, rows } = comparison;
  const ranked = [...(comparison.reference ?? [])].sort(
    (a, b) => (b.accuracy ?? -1) - (a.accuracy ?? -1),
  );
  const modelPairs = ref ? pairs.filter((p) => !p.columns.includes(ref)) : pairs;
  const rule =
    tolerance == null
      ? "Exact matches"
      : `Within ${formatNumber(tolerance)}${columns.every((name) => dataset.columns.find((c) => c.name === name)?.type === "DATE") ? " days" : ""}`;
  const names = columns.map(columnLabel).join(" · ");
  const allMissing = columns.map((c) => `${ident(c)} IS NULL`).join(" AND ");
  const partial =
    agreement.all_agree.where && agreement.disagree.where
      ? `NOT (${agreement.all_agree.where}) AND NOT (${agreement.disagree.where}) AND NOT (${allMissing})`
      : null;
  const inspect = (p: Pair) => {
    setPairKey(JSON.stringify(p.columns));
    setView("pair");
  };

  return (
    <div className="flex flex-col text-sm">
      <section className="space-y-3 border-b px-3 py-3" aria-label="Agreement summary">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="font-medium">
            {percent(agreement.rate)} all-column agreement{" "}
            <span className="font-normal text-muted-foreground">· {rule}</span>
          </span>
          <span className="text-xs text-muted-foreground">
            {formatNumber(agreement.all_agree.rows + agreement.disagree.rows)} comparable /{" "}
            {formatNumber(rows)} total
          </span>
        </div>
        <Progress value={(agreement.rate ?? 0) * 100} aria-label="Overall agreement" />
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
          <Count
            rows={agreement.all_agree.rows}
            where={agreement.all_agree.where}
            label={`All agree · ${rule} · ${names}`}
            columns={columns}
            onFilter={onFilter}
          >
            agree
          </Count>
          <Count
            rows={agreement.disagree.rows}
            where={agreement.disagree.where}
            label={`Disagree · ${rule} · ${names}`}
            columns={columns}
            onFilter={onFilter}
          >
            disagree
          </Count>
          <Count
            rows={agreement.partly_answered}
            where={partial}
            label={`Partial answers, no conflict · ${names}`}
            columns={columns}
            onFilter={onFilter}
          >
            partial, no conflict
          </Count>
          <Count
            rows={agreement.not_answered}
            where={allMissing}
            label={`All answers missing · ${names}`}
            columns={columns}
            onFilter={onFilter}
          >
            unanswered
          </Count>
        </div>
        <p className="text-xs text-muted-foreground">
          {names}
          {ref ? " (reference included)" : ""}. Agreement excludes partial rows without a conflict
          and unanswered rows. Counts open the underlying rows.
        </p>
      </section>
      <Tabs value={view} onValueChange={setView} className="gap-0">
        <div className="border-b px-3 py-2">
          <TabsList variant="line">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="pair">Inspect pair</TabsTrigger>
            <TabsTrigger value="values">Distributions</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="overview" className="space-y-5 p-3">
          {ref && (
            <section className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-medium">Match to {columnLabel(ref)}</h3>
                <span className="text-xs text-muted-foreground">
                  Highest match first · reference is not necessarily truth
                </span>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Column / inspect</TableHead>
                    <TableHead>Match rate</TableHead>
                    <TableHead className="text-right">Compared</TableHead>
                    <TableHead className="text-right">Different</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ranked.map((r) => (
                    <TableRow key={r.column}>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="max-w-56 justify-start px-0 text-sm"
                          onClick={() =>
                            inspect(
                              pairs.find(
                                (p) => p.columns.includes(r.column) && p.columns.includes(ref),
                              )!,
                            )
                          }
                        >
                          <span className="truncate" title={r.column}>
                            {columnLabel(r.column)}
                          </span>
                          <ArrowRightIcon />
                        </Button>
                      </TableCell>
                      <TableCell>
                        <Rate rate={r.accuracy} label={`${columnLabel(r.column)} match rate`} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(r.compared)} / {formatNumber(rows)}
                        <div className="text-xs text-muted-foreground">
                          <Count
                            rows={rows - r.compared}
                            where={`${ident(r.column)} IS NULL OR ${ident(ref)} IS NULL`}
                            label={`Missing ${columnLabel(r.column)} or ${columnLabel(ref)}`}
                            columns={[r.column, ref]}
                            onFilter={onFilter}
                          >
                            missing either answer
                          </Count>
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Count
                          rows={r.compared - r.correct}
                          where={r.wrong}
                          columns={[r.column, ref]}
                          label={`${columnLabel(r.column)} ≠ ${columnLabel(ref)} · ${rule}`}
                          onFilter={onFilter}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="text-xs text-muted-foreground">
                Select a column to inspect its confusions and per-label precision / recall. Rates
                use rows where both columns have answers.
              </p>
            </section>
          )}
          {modelPairs.length > 0 && (
            <section className="space-y-2">
              <h3 className="font-medium">
                {ref ? "Between compared columns" : "Pairwise agreement"}
              </h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Pair / inspect</TableHead>
                    <TableHead>Agreement</TableHead>
                    <TableHead className="text-right">Compared</TableHead>
                    <TableHead className="text-right">Different</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...modelPairs]
                    .sort((a, b) => (a.rate ?? 1) - (b.rate ?? 1))
                    .map((p) => (
                      <TableRow key={JSON.stringify(p.columns)}>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="max-w-72 justify-start px-0 text-xs"
                            onClick={() => inspect(p)}
                          >
                            <span className="truncate" title={p.columns.join(" · ")}>
                              {p.columns.map(columnLabel).join(" · ")}
                            </span>
                            <ArrowRightIcon />
                          </Button>
                        </TableCell>
                        <TableCell>
                          <Rate rate={p.rate} label="Pair agreement" />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatNumber(p.compared)} / {formatNumber(rows)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Count
                            rows={p.compared - p.agree}
                            where={p.disagree}
                            columns={p.columns}
                            label={`${p.columns.map(columnLabel).join(" ≠ ")} · ${rule}`}
                            onFilter={onFilter}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
              <p className="text-xs text-muted-foreground">
                Lowest agreement first. Missing answers are excluded from each pair’s denominator.
              </p>
            </section>
          )}
        </TabsContent>
        <TabsContent value="pair" className="p-3">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Label htmlFor="inspect-pair" className="text-xs">
              Pair
            </Label>
            <Select
              value={pairKey}
              onValueChange={(value) => value && setPairKey(value)}
              items={pairs.map((p) => ({
                value: JSON.stringify(p.columns),
                label: p.columns.map(columnLabel).join(" · "),
              }))}
            >
              <SelectTrigger id="inspect-pair" size="sm" className="max-w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {pairs.map((p) => (
                  <SelectItem key={JSON.stringify(p.columns)} value={JSON.stringify(p.columns)}>
                    {p.columns.map(columnLabel).join(" · ")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <PairDetail
            key={pairKey}
            dataset={dataset}
            comparison={comparison}
            pair={pair}
            tolerance={tolerance ?? null}
            rule={rule}
            onFilter={onFilter}
          />
        </TabsContent>
        <TabsContent value="values" className="space-y-2 p-3">
          <Distributions comparison={comparison} dataset={dataset} onFilter={onFilter} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function PairDetail({
  dataset,
  comparison,
  pair,
  tolerance,
  rule,
  onFilter,
}: {
  dataset: Dataset;
  comparison: Comparison;
  pair: Pair;
  tolerance: number | null;
  rule: string;
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
            tolerance,
          },
    [comparison.columns.length, pair.columns, tolerance],
  );
  const numeric = pair.columns.every((name) =>
    /^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|FLOAT|DOUBLE|DECIMAL.*|DATE)$/.test(
      dataset.columns.find((c) => c.name === name)?.type ?? "",
    ),
  );
  const result = useComparison(dataset.id, numeric ? undefined : request, dataset.run?.done);
  const data = comparison.columns.length === 2 ? comparison : result.data;
  const reference = comparison.reference?.find(
    (r) => r.column === pair.columns[0] && pair.columns[1] === comparison.columns.at(-1),
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="font-medium">{percent(pair.rate)} agree</span>
        <span className="text-xs text-muted-foreground">
          {formatNumber(pair.compared)} / {formatNumber(comparison.rows)} rows have both answers ·{" "}
          {rule}
        </span>
        <Count
          rows={pair.compared - pair.agree}
          where={pair.disagree}
          columns={pair.columns}
          label={`${pair.columns.map(columnLabel).join(" ≠ ")} · ${rule}`}
          onFilter={onFilter}
        >
          different
        </Count>
      </div>
      {numeric ? (
        <NumericComparison
          dataset={dataset}
          pair={pair}
          tolerance={tolerance}
          onFilter={onFilter}
        />
      ) : result.error ? (
        <Alert variant="destructive">
          <AlertDescription>{result.error}</AlertDescription>
          <Button size="sm" variant="outline" onClick={result.retry}>
            Retry
          </Button>
        </Alert>
      ) : !data ? (
        <div role="status" className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Loading pair…
        </div>
      ) : (
        <Crosstab
          comparison={data}
          pair={pair}
          tolerance={tolerance}
          reference={reference ? pair.columns[1] : null}
          onFilter={onFilter}
        />
      )}
      {reference && tolerance === null && (
        <section className="space-y-2">
          <h3 className="font-medium">Which labels are missed?</h3>
          <p className="text-xs text-muted-foreground">
            Worst recall first. Precision: of this model’s predictions, how many match? Recall: of
            the reference’s labels, how many are found? Both exclude rows missing either answer.
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Reference label</TableHead>
                <TableHead className="text-right">Precision</TableHead>
                <TableHead className="text-right">Recall</TableHead>
                <TableHead className="text-right">Reference</TableHead>
                <TableHead className="text-right">Predicted</TableHead>
                <TableHead className="text-right">Correct</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...reference.values]
                .sort((a, b) => (a.recall ?? 2) - (b.recall ?? 2))
                .map((v) => (
                  <TableRow key={v.value}>
                    <TableCell className="max-w-48 truncate" title={v.value}>
                      {v.value || '""'}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {percent(v.precision)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <Rate rate={v.recall} label={`${v.value} recall`} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(v.support)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(v.predicted)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(v.correct)}
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">
            Up to 20 most common reference labels. “—” means there is no denominator, not zero
            accuracy.
          </p>
        </section>
      )}
    </div>
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
  const complete = represented === pair.compared;
  const max = Math.max(1, ...cells.map((c) => c.rows));
  return (
    <section className="space-y-2">
      <h3 className="font-medium">{reference ? "Confusion table" : "Value combinations"}</h3>
      <p className="text-xs text-muted-foreground">
        Rows: {columnLabel(a)}
        {reference ? " (prediction)" : ""} · Columns: {columnLabel(b)}
        {reference ? " (reference)" : ""}. Stronger tint = more rows. Accent = identical value;
        neutral = different value. Click a count to inspect.
      </p>
      {tolerance !== null && (
        <p className="text-xs text-muted-foreground">
          Raw value combinations; tint shows frequency, not tolerance agreement. The agreement rate
          above uses the active tolerance.
        </p>
      )}
      {!cells.length ? (
        <p className="py-3 text-muted-foreground">No rows have answers in both columns.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                {columnLabel(a)} ↓ / {columnLabel(b)} →
              </TableHead>
              {across.map((v) => (
                <TableHead key={v} className="max-w-32 truncate text-right" title={v}>
                  {v || '""'}
                </TableHead>
              ))}
              <TableHead className="text-right">Shown total</TableHead>
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
                            backgroundColor: `color-mix(in oklch, ${row === col ? "var(--primary)" : "var(--muted-foreground)"} ${8 + (25 * c.rows) / max}%, transparent)`,
                          }}
                          aria-label={`${columnLabel(a)}: ${row}; ${columnLabel(b)}: ${col}; ${formatNumber(c.rows)} rows`}
                          onClick={() =>
                            onFilter(
                              [
                                {
                                  where: c.where,
                                  label: `${columnLabel(a)} = ${row}, ${columnLabel(b)} = ${col}`,
                                },
                              ],
                              pair.columns,
                            )
                          }
                        >
                          {tolerance === null && row === col && (
                            <CheckIcon aria-label="Same value" className="size-3" />
                          )}
                          {formatNumber(c.rows)}
                        </Button>
                      ) : (
                        <span className="px-2 text-muted-foreground">{complete ? "0" : "—"}</span>
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
              <TableCell>Shown total</TableCell>
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
        {!complete &&
          " Only the 50 most common combinations are available; — means not shown, not necessarily zero."}
        {tolerance === null && " ✓ marks identical displayed values."}
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
        Counts and bars share the same denominator: all {formatNumber(comparison.rows)} rows. Empty
        answers are separate; “Other values” combines values outside the most common 20.
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
                  <div className="mb-1 text-xs tabular-nums">{formatNumber(v.counts[c] ?? 0)}</div>
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

function Rate({ rate, label }: { rate: number | null; label: string }) {
  return (
    <div className="flex min-w-28 items-center gap-2">
      <Progress value={(rate ?? 0) * 100} aria-label={label} className="w-24" />
      <span className="tabular-nums">{percent(rate)}</span>
    </div>
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
      onClick={() => onFilter([{ where, label }], columns)}
    >
      {formatNumber(rows)}
      {children && <> {children}</>}
      <ArrowRightIcon className="size-3" />
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
