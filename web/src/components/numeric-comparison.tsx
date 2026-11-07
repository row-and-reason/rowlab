"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  Rectangle,
  useXAxisScale,
  XAxis,
  YAxis,
  type BarShapeProps,
} from "recharts";
import { ChevronDownIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type Comparison } from "@/lib/api/client";
import { type WhereFilter } from "@/lib/sql";

const metric = (n: number | null) =>
  n === null
    ? "—"
    : n !== 0 && (Math.abs(n) >= 1e6 || Math.abs(n) < 1e-4)
      ? n.toExponential(3)
      : n.toLocaleString("en-US", { maximumSignificantDigits: 4 });

/** All metrics, bins and row predicates come from the comparison API. */
export function NumericComparison({
  pair,
  tolerance,
  onFilter,
}: {
  pair: Comparison["pairs"][number];
  tolerance: number | null;
  onFilter: (filters: WhereFilter[], columns: string[]) => void;
}) {
  const stats = pair.numeric!;
  if (!stats.finite_pairs)
    return <p className="py-3 text-muted-foreground">No finite paired answers to summarize.</p>;
  const scale = Math.max(
    ...stats.histogram.flatMap((b) => [Math.abs(b.lower), Math.abs(b.upper)]),
    tolerance ?? 0,
    Number.MIN_VALUE,
  );
  const bins = stats.histogram.map((b) => ({
    ...b,
    center: b.lower / scale / 2 + b.upper / scale / 2,
    plotLower: b.lower / scale,
    plotUpper: b.upper / scale,
    matchedCount: b.matched.rows,
    differentCount: b.different.rows,
    range: `${metric(b.lower)} to ${metric(b.upper)}`,
  }));
  const low = Math.min(bins[0].plotLower, 0),
    high = Math.max(bins.at(-1)!.plotUpper, 0);
  const domain: [number, number] = low === high ? [-1, 1] : [low, high];
  const inspect = (bin: (typeof bins)[number], kind?: "matched" | "different") => {
    const subset = kind ? bin[kind] : bin;
    if (subset.where && subset.rows)
      onFilter(
        [
          {
            where: subset.where,
            label: `${stats.difference}: ${bin.range}${kind ? ` · ${kind}` : ""}`,
          },
        ],
        pair.columns,
      );
  };
  return (
    <section className="space-y-4">
      <dl className="flex flex-wrap gap-x-10 gap-y-3">
        <div>
          <dt className="text-xs text-muted-foreground">Signed mean difference</dt>
          <dd className="mt-1 font-medium tabular-nums">
            {(stats.bias ?? 0) > 0 ? "+" : ""}
            {metric(stats.bias)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">95th percentile absolute difference</dt>
          <dd className="mt-1 font-medium tabular-nums">{metric(stats.p95_absolute_difference)}</dd>
        </div>
      </dl>
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-medium">Difference distribution</h3>
          <span className="text-xs text-muted-foreground">{stats.finite_pairs} finite pairs</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Difference: {stats.difference}
          {stats.unit === "days" ? " · days" : ""}
        </p>
        <span className="block text-xs text-muted-foreground">Rows</span>
        <ChartContainer
          config={{
            matchedCount: {
              label: tolerance !== null ? "Within tolerance" : "Exact matches",
              color: "var(--muted-foreground)",
            },
            differentCount: { label: "Different", color: "var(--primary)" },
          }}
          className="h-64 w-full aspect-auto"
        >
          <BarChart
            data={bins}
            margin={{ top: 28, right: 16, bottom: 12, left: 0 }}
            accessibilityLayer
          >
            <CartesianGrid vertical={false} />
            <XAxis
              type="number"
              dataKey="center"
              domain={domain}
              tickFormatter={(v) => metric(Number(v) * scale)}
              tick={{ fill: "var(--foreground)", fillOpacity: 0.8 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              allowDecimals={false}
              tickLine={false}
              axisLine={false}
              width={42}
              tick={{ fill: "var(--foreground)", fillOpacity: 0.8 }}
            />
            <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeDasharray="3 3" />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.range ?? "Difference"}
                />
              }
            />
            <Bar
              dataKey="matchedCount"
              stackId="rows"
              fill="var(--muted-foreground)"
              fillOpacity={0.4}
              isAnimationActive={false}
              shape={<IntervalBar />}
              onClick={(_, index) => inspect(bins[index], "matched")}
              cursor="pointer"
            />
            <Bar
              dataKey="differentCount"
              stackId="rows"
              fill="var(--primary)"
              fillOpacity={0.85}
              isAnimationActive={false}
              shape={<IntervalBar />}
              onClick={(_, index) => inspect(bins[index], "different")}
              cursor="pointer"
            />
          </BarChart>
        </ChartContainer>
        <div className="flex flex-wrap items-center gap-5 text-xs">
          {(["matched", "different"] as const).map((kind) => (
            <Button
              key={kind}
              variant="ghost"
              size="sm"
              className="px-0 text-xs"
              disabled={!stats[kind].rows}
              onClick={() =>
                onFilter(
                  [
                    {
                      where: stats[kind].where!,
                      label: `${stats.difference} · ${kind}${tolerance !== null ? ` · tolerance ${tolerance}` : ""}`,
                    },
                  ],
                  pair.columns,
                )
              }
            >
              <span
                className={`size-2.5 rounded-sm ${kind === "matched" ? "bg-muted-foreground/40" : "bg-primary"}`}
              />
              {stats[kind].rows}{" "}
              {kind === "matched"
                ? tolerance !== null
                  ? `within ±${metric(tolerance)}`
                  : "exact matches"
                : "different"}
              {kind === "matched"
                ? ` · ${((100 * stats.matched.rows) / stats.finite_pairs).toFixed(1)}%`
                : ""}
            </Button>
          ))}
          <span className="text-muted-foreground">Select a bar segment to inspect rows.</span>
        </div>
      </div>
      <Collapsible>
        <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="px-0 text-xs" />}>
          <ChevronDownIcon className="size-3" /> Inspect bins and exact counts
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Difference interval</TableHead>
                <TableHead className="text-right">All rows</TableHead>
                <TableHead className="text-right">Matched</TableHead>
                <TableHead className="text-right">Different</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bins.map((b, i) => (
                <TableRow key={i}>
                  <TableCell className="tabular-nums">
                    [{metric(b.lower)}, {metric(b.upper)}
                    {b.upper_inclusive ? "]" : ")"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!b.rows}
                      onClick={() => inspect(b)}
                      aria-label={`Inspect ${b.rows} rows in bin ${i + 1}`}
                      className="text-xs tabular-nums"
                    >
                      {b.rows}
                    </Button>
                  </TableCell>
                  {(["matched", "different"] as const).map((kind) => (
                    <TableCell key={kind} className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!b[kind].rows}
                        onClick={() => inspect(b, kind)}
                        aria-label={`Inspect ${kind} rows in bin ${i + 1}`}
                      >
                        {b[kind].rows}
                      </Button>
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="pt-3 text-xs text-muted-foreground">
            Largest absolute difference: {metric(stats.max_absolute_difference)}.{" "}
            {stats.non_finite_pairs} non-finite pairs excluded. Displayed bounds are rounded; row
            filters use full precision.
          </p>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}

/** Use actual interval edges, rather than treating the bin's midpoint as a value. */
function IntervalBar(props: Partial<BarShapeProps>) {
  const scale = useXAxisScale();
  const bin = props.payload as { plotLower: number; plotUpper: number } | undefined;
  if (!scale || !bin) return null;
  const left = scale(bin.plotLower),
    right = scale(bin.plotUpper);
  if (left === undefined || right === undefined) return null;
  const width = Math.max(2, right - left - 1);
  return (
    <Rectangle
      x={left === right ? left - 3 : left}
      y={props.y}
      width={left === right ? 6 : width}
      height={props.height}
      fill={props.fill}
      fillOpacity={props.fillOpacity}
    />
  );
}
