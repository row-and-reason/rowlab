"use client";

import { PlusIcon } from "lucide-react";

import { modelSlug, TYPES } from "@/components/answer-settings";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Run, RunSummary, Scope } from "@/lib/api/client";
import { formatAgo, formatNumber, formatUsd } from "@/lib/format";

/** The Runs tab: a dataset's runs, newest first. */
export function RunsList({
  runs,
  selectedId,
  onOpen,
  onNew,
}: {
  runs: RunSummary[];
  selectedId: string | null;
  onOpen: (run: RunSummary) => void;
  onNew: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <Button size="sm" variant="ghost" onClick={onNew}>
          <PlusIcon data-icon="inline-start" />
          New run
        </Button>
      </div>
      {runs.length === 0 ? (
        <Empty className="flex-1">
          <EmptyHeader>
            <EmptyTitle>No runs yet</EmptyTitle>
            <EmptyDescription>Set up tasks on the right and press Run.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ItemGroup className="min-h-0 flex-1 gap-0.5 overflow-auto p-2">
          {runs.map((run) => (
            <Item
              key={run.id}
              size="xs"
              variant={run.id === selectedId ? "muted" : "default"}
              render={<button type="button" className="text-left" onClick={() => onOpen(run)} />}
            >
              <ItemContent className="min-w-0">
                <ItemTitle>
                  Run #{run.number}
                  <span className="font-normal text-muted-foreground">
                    {formatAgo(run.created_at)}
                  </span>
                </ItemTitle>
                <ItemDescription className="truncate text-xs">
                  {statusText(run)} · {formatNumber(run.row_count)} rows ·{" "}
                  {run.config.tasks.map((t) => t.column).join(", ")}
                </ItemDescription>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
      )}
    </div>
  );
}

/** A finished run, read-only: what it ran on, what it asked, and what it cost. */
export function RunDetails({ run }: { run: Run }) {
  const failures = run.rows.flatMap((r) => Object.values(r.errors));
  return (
    <FieldGroup className="gap-5 p-4">
      <p className="text-sm text-muted-foreground">
        {statusText(run)} · {formatNumber(run.row_count)} rows · {formatAgo(run.created_at)}
        <br />
        {describeScope(run.config.scope)}
      </p>
      {run.status === "running" && (
        <Progress value={run.total ? (100 * run.done) / run.total : 0} aria-label="Run progress" />
      )}
      {run.error && (
        <Alert variant="destructive">
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}
      {run.config.tasks.map((task) => (
        <Field key={task.id}>
          <FieldLabel>
            {task.column}
            <span className="font-normal text-muted-foreground">
              {TYPES.find((t) => t.value === task.type)?.label} ·{" "}
              {task.models.map(modelSlug).join(", ")}
            </span>
          </FieldLabel>
          <p className="rounded-lg bg-muted p-3 text-sm whitespace-pre-wrap select-text">
            {task.template}
          </p>
          {task.options.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {task.type === "scale" ? "Levels" : "Options"}:{" "}
              {task.options.map((o) => o.name).join(", ")}
            </p>
          )}
        </Field>
      ))}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Task</TableHead>
            <TableHead>Model</TableHead>
            <TableHead className="text-right">Failed</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {run.costs.map((c) => (
            <TableRow key={`${c.task_id} ${c.model}`}>
              <TableCell>{run.config.tasks.find((t) => t.id === c.task_id)?.column}</TableCell>
              <TableCell>{modelSlug(c.model)}</TableCell>
              <TableCell className="text-right">{c.failed || ""}</TableCell>
              <TableCell className="text-right">{formatUsd(c.cost)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {failures.length > 0 && (
        <Alert variant="destructive">
          <AlertDescription>{failures[0]}</AlertDescription>
        </Alert>
      )}
    </FieldGroup>
  );
}

/** Where a run stands: its cost when done, its progress while running. */
function statusText(run: RunSummary): string {
  if (run.status === "running") {
    return `Running, ${formatNumber(run.done)} of ${formatNumber(run.total)} answers`;
  }
  if (run.status === "failed") return "Failed";
  return formatUsd(run.cost);
}

/** A scope in words, e.g. “city = Tokyo · spend, high to low · first 8 rows”. */
function describeScope(scope: Scope): string {
  const parts = [
    scope.search && `“${scope.search}”`,
    ...scope.filters.map((f) =>
      [f.column, f.op.replaceAll("_", " "), f.value ?? ""].join(" ").trim(),
    ),
    ...scope.sort.map((s) => `${s.column}, ${s.desc ? "high to low" : "low to high"}`),
    scope.limit && `first ${formatNumber(scope.limit)} rows`,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "All rows";
}
