"use client";

import { Bar, BarChart, CartesianGrid, ReferenceArea, ReferenceLine, XAxis, YAxis } from "recharts";
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
  n === null ? "—" : n.toLocaleString("en-US", { maximumSignificantDigits: 4 });

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
  const bins = stats.histogram.map((b) => ({
    ...b,
    center: (b.lower + b.upper) / 2,
    range: `${metric(b.lower)} to ${metric(b.upper)}`,
  }));
  const low = bins[0].lower,
    high = bins.at(-1)!.upper;
  const extent = Math.max(Math.abs(low), Math.abs(high), tolerance ?? 0, 0.001);
  const domain: [number, number] =
    low === high ? [low - extent / 2, high + extent / 2] : [Math.min(low, 0), Math.max(high, 0)];
  const inspect = (bin: (typeof bins)[number]) =>
    bin.where &&
    onFilter(
      [
        {
          where: bin.where,
          label: `${stats.difference}: ${bin.range}${stats.unit === "days" ? " days" : ""}`,
        },
      ],
      pair.columns,
    );
  return (
    <section className="space-y-4">
      <dl className="flex flex-wrap gap-x-10 gap-y-3">
        <div>
          <dt className="text-xs text-muted-foreground">Mean absolute difference</dt>
          <dd className="mt-1 font-medium tabular-nums">
            {metric(stats.mean_absolute_difference)}
          </dd>
        </div>
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
          {stats.difference}
          {stats.unit === "days" ? " · days" : ""} · positive means the first named column is
          higher.
        </p>
        <ChartContainer
          config={{ rows: { label: "Rows", color: "var(--primary)" } }}
          className="h-64 w-full aspect-auto"
        >
          <BarChart
            data={bins}
            margin={{ top: 12, right: 16, bottom: 12, left: 0 }}
            accessibilityLayer
          >
            <CartesianGrid vertical={false} />
            <XAxis
              type="number"
              dataKey="center"
              domain={domain}
              tickFormatter={metric}
              tickLine={false}
              axisLine={false}
            />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={38} />
            {tolerance !== null && (
              <ReferenceArea
                x1={Math.max(domain[0], -tolerance)}
                x2={Math.min(domain[1], tolerance)}
                fill="var(--primary)"
                fillOpacity={0.1}
              />
            )}
            <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeDasharray="3 3" />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.range ?? "Difference"}
                />
              }
            />
            <Bar
              dataKey="rows"
              fill="var(--primary)"
              fillOpacity={0.75}
              maxBarSize={48}
              isAnimationActive={false}
              onClick={(_, index) => inspect(bins[index])}
              cursor="pointer"
            />
          </BarChart>
        </ChartContainer>
        <p className="text-xs text-muted-foreground">
          Click a bar to inspect its rows.
          {tolerance !== null
            ? ` Shaded range: ±${metric(tolerance)}. A bar may contain values on both sides of the tolerance boundary.`
            : " Dashed line: no difference."}
        </p>
      </div>
      <Collapsible>
        <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="px-0 text-xs" />}>
          Inspect bins and exact counts
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Difference interval</TableHead>
                <TableHead className="text-right">Rows / inspect</TableHead>
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
