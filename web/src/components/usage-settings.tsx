"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";

import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Usage } from "@/lib/api/client";
import { errorMessage, formatBytes, formatNumber, formatUsd } from "@/lib/format";

const chartConfig = {
  answers: { label: "Answers", color: "var(--primary)" },
} satisfies ChartConfig;

/** A month's answers and spend, by day, model and person, and the storage datasets take. */
export function UsageSettings() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [usage, setUsage] = useState<Usage>();
  const [error, setError] = useState<{ month: string; message: string }>();
  // Bumped by "Try again", to load the month once more.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    api
      .GET("/v1/settings/usage", { params: { query: { month } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (data) setUsage(data);
        else setError({ month, message: errorMessage(error) });
      })
      .catch(() => current && setError({ month, message: "Could not reach rowlab." }));
    return () => {
      current = false;
    };
  }, [month, attempt]);

  const loaded = usage?.month === month ? usage : undefined;
  const failed = error?.month === month && !loaded ? error.message : undefined;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-1">
        <TooltipButton
          label="Month before"
          variant="ghost"
          size="icon-sm"
          onClick={() => setMonth(shift(month, -1))}
        >
          <ChevronLeftIcon />
        </TooltipButton>
        <span className="w-32 text-center text-sm font-medium">{monthName(month)}</span>
        <TooltipButton
          label="Month after"
          variant="ghost"
          size="icon-sm"
          disabled={month >= new Date().toISOString().slice(0, 7)}
          onClick={() => setMonth(shift(month, 1))}
        >
          <ChevronRightIcon />
        </TooltipButton>
        {loaded && (
          <span className="ml-auto text-xs text-muted-foreground">
            {loaded.scope === "organisation" ? "Your organisation's runs" : "Your runs"} · UTC
          </span>
        )}
      </div>
      {failed ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Usage didn&apos;t load</EmptyTitle>
            <EmptyDescription>{failed}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setError(undefined);
                setAttempt((n) => n + 1);
              }}
            >
              Try again
            </Button>
          </EmptyContent>
        </Empty>
      ) : loaded ? (
        <MonthUsage usage={loaded} />
      ) : (
        <Spinner />
      )}
    </div>
  );
}

/** A month's figures, chart and breakdowns. */
function MonthUsage({ usage }: { usage: Usage }) {
  const { total } = usage;
  // Every day of the month, so the days without usage show as gaps.
  const days = useMemo(() => {
    const [year, number] = usage.month.split("-").map(Number);
    const count = new Date(Date.UTC(year, number, 0)).getUTCDate();
    const used = new Map(usage.by_day.map((d) => [d.day, d]));
    return Array.from({ length: count }, (_, i) => {
      const day = `${usage.month}-${String(i + 1).padStart(2, "0")}`;
      return { day, answers: used.get(day)?.answers ?? 0, cost: used.get(day)?.cost ?? 0 };
    });
  }, [usage]);

  return (
    <>
      <dl className="grid grid-cols-4 gap-4">
        <Figure label="Answers" value={formatNumber(total.answers)}>
          {total.cached > 0 && `${formatNumber(total.cached)} from the cache, free`}
        </Figure>
        <Figure label="Spent" value={formatUsd(total.cost)}>
          {total.failed > 0 && `${formatNumber(total.failed)} failed`}
        </Figure>
        <Figure label="Tokens" value={formatNumber(total.input_tokens + total.output_tokens)}>
          {formatNumber(total.input_tokens)} in · {formatNumber(total.output_tokens)} out
        </Figure>
        <Figure label="Storage" value={formatBytes(usage.storage_bytes)}>
          The organisation&apos;s datasets, now
        </Figure>
      </dl>

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Answers by day</h3>
        <ChartContainer config={chartConfig} className="aspect-auto h-40 w-full">
          <BarChart data={days} margin={{ left: 0, right: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="day"
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              tickFormatter={(day: string) => String(Number(day.slice(8)))}
            />
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  labelFormatter={(_, payload) => dayName(payload[0]?.payload.day)}
                  formatter={(value, _, item) => (
                    <span className="tabular-nums">
                      {formatNumber(Number(value))} answers · {formatUsd(item.payload.cost)}
                    </span>
                  )}
                />
              }
            />
            <Bar dataKey="answers" fill="var(--color-answers)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </section>

      <Breakdown
        title="By model"
        rows={usage.by_model.map((m) => ({ key: m.model, name: m.model, ...m }))}
      />
      {usage.scope === "organisation" && usage.by_person.some((p) => p.user) && (
        <Breakdown
          title="By person"
          rows={usage.by_person.map((p) => ({
            key: p.user?.id ?? "nobody",
            name: p.user ? `${p.user.name} · ${p.user.email}` : "Started before sign-in",
            ...p,
          }))}
        />
      )}
    </>
  );
}

function Figure({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      <dd className="text-xs text-muted-foreground">{children}</dd>
    </div>
  );
}

function Breakdown({
  title,
  rows,
}: {
  title: string;
  rows: { key: string; name: string; answers: number; cached: number; cost: number }[];
}) {
  if (rows.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead />
            <TableHead className="text-right">Answers</TableHead>
            <TableHead className="text-right">From the cache</TableHead>
            <TableHead className="text-right">Spent</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell className="max-w-64 truncate">{row.name}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.answers)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.cached)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatUsd(row.cost)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

/** `2026-11` moved by `months`. */
function shift(month: string, months: number): string {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 1 + months, 1)).toISOString().slice(0, 7);
}

function monthName(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function dayName(day: string | undefined): string {
  if (!day) return "";
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
