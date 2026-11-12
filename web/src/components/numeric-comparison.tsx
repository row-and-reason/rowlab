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
import { Button } from "@/components/ui/button";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import type { InspectRows, Pair } from "@/lib/comparison";

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
  pair: Pair;
  tolerance: number | null;
  onFilter: InspectRows;
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
        </div>
      </div>
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
